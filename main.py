import os
import asyncio
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
import pytz
from collections import Counter
import aiohttp
from telegram import Bot
from telegram.error import TelegramError
from dotenv import load_dotenv

load_dotenv()

# ───────────────────────────────────────────────
# CONFIGURAÇÕES
# ───────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7345209825:AAE54I0tSUEdomWNOVkdTOFDnvY7jKBC4o0")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "-1003683356410")
API_URL = "https://api-cs.casino.org/svc-evolution-game-events/api/bacbo/latest"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json',
    'Accept-Language': 'en-US,en;q=0.9',
}

ANGOLA_TZ = pytz.timezone('Africa/Luanda')

OUTCOME_MAP = {
    "PlayerWon": "🔵", "BankerWon": "🔴", "Tie": "🟡",
    "🔵": "🔵", "🔴": "🔴", "🟡": "🟡",
}

API_POLL_INTERVAL      = 3
SIGNAL_CYCLE_INTERVAL  = 6
ANALISE_REFRESH_INTERVAL = 15
MIN_SCORE_TO_SIGNAL = 14.0
COOLDOWN_AFTER_SIGNAL_SECONDS = 20

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)-5s | %(message)s')
logger = logging.getLogger("BacBoAssertiveBot")
bot = Bot(token=TELEGRAM_BOT_TOKEN)

state: Dict[str, Any] = {
    "history": [],
    "history_sums": [],
    "last_round_id": None,
    "last_processed_round_id": None,
    "waiting_for_result": False,
    "signal_round_id": None,
    "last_signal_color": None,
    "martingale_count": 0,
    "entrada_message_id": None,
    "gale_message_ids": [],
    "greens_seguidos": 0,
    "total_greens": 0,
    "greens_sem_gale": 0,
    "greens_gale_1": 0,
    "greens_gale_2": 0,
    "total_empates": 0,           # apenas empates fora de sinal ativo
    "total_losses": 0,
    "signal_cooldown": False,
    "signal_cooldown_end": 0.0,
    "analise_message_id": None,
    "last_reset_date": None,
    "last_analise_refresh": 0.0,
    "player_score_last": None,
    "banker_score_last": None,
}

# ───────────────────────────────────────────────
# FUNÇÕES AUXILIARES
# ───────────────────────────────────────────────

def count_last_consecutive(hist: List[str], cor: str) -> int:
    count = 0
    for i in range(len(hist)-1, -1, -1):
        if hist[i] == cor:
            count += 1
        elif hist[i] != "🟡":
            break
    return count

def count_without_tie(hist: List[str]) -> int:
    count = 0
    for i in range(len(hist)-1, -1, -1):
        if hist[i] != "🟡":
            count += 1
        else:
            break
    return count

def is_new_round():
    return state["last_round_id"] != state["last_processed_round_id"]

def should_reset_placar() -> bool:
    now = datetime.now(ANGOLA_TZ)
    if state["last_reset_date"] != now.date() or state["total_losses"] >= 10:
        state["last_reset_date"] = now.date()
        return True
    return False

def reset_placar_if_needed():
    if should_reset_placar():
        for k in ["total_greens", "greens_sem_gale", "greens_gale_1", "greens_gale_2",
                  "total_empates", "total_losses", "greens_seguidos"]:
            state[k] = 0
        logger.info("Placar resetado")

def calcular_acertividade() -> str:
    total = state["total_greens"] + state["total_losses"]
    return "—" if total == 0 else f"{state['total_greens']/total*100:.1f}%"

def format_placar() -> str:
    return (
        "🏆 <b>RESUMO</b> 🏆\n"
        f"🎯 Greens: <b>{state['total_greens']}</b>  |  Acertividade: <b>{calcular_acertividade()}</b>\n"
        f"────────────────────\n"
        f"⛔ Losses: <b>{state['total_losses']}</b>\n"
    )

def format_analise_text() -> str:
    return "🎲 <b>ANALISANDO PADRÕES ASSERTIVOS...</b> 🎲\n\n<i>Aguarde sinal baseado em estratégias reais</i>"

# ───────────────────────────────────────────────
# PADRÕES (adicione todos os que você tinha antes)
# ───────────────────────────────────────────────

PATTERNS = [
    (1,  "Triplo Jogador → Banker", lambda h,ps,bs: count_last_consecutive(h,"🔵") >= 3, "🔴", 8.8),
    (2,  "Intercalado PB PB → Banker", lambda h,ps,bs: len(h)>=4 and h[-4:] == ["🔵","🔴","🔵","🔴"], "🔴", 8.5),
    (4,  "Recuperação Empate → Anterior", lambda h,ps,bs: len(h)>=2 and h[-1]=="🟡" and h[-2] in ["🔵","🔴"], lambda h,ps,bs: h[-2], 8.2),
    (6,  "Padrão 2-2 PPBB → Banker", lambda h,ps,bs: len(h)>=4 and h[-4:] == ["🔵","🔵","🔴","🔴"], "🔴", 8.7),
    # ... adicione os outros padrões aqui
    (109, "Tendência Forte Banker >70% last10 → Banker", lambda h,ps,bs: len(h)>=10 and Counter(h[-10:])["🔴"]/10 >=0.7, "🔴", 9.1),
]

# ───────────────────────────────────────────────
# FUNÇÕES TELEGRAM
# ───────────────────────────────────────────────

async def send_to_channel(text: str, parse_mode="HTML") -> Optional[int]:
    try:
        msg = await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=text,
            parse_mode=parse_mode,
            disable_web_page_preview=True
        )
        return msg.message_id
    except Exception as e:
        logger.error(f"Erro envio Telegram: {e}")
        return None

async def delete_messages(message_ids: List[int]):
    for mid in message_ids[:]:
        try:
            await bot.delete_message(TELEGRAM_CHANNEL_ID, mid)
        except:
            pass

async def clear_gale_messages():
    await delete_messages(state["gale_message_ids"])
    state["gale_message_ids"] = []

async def delete_analise_message():
    if state["analise_message_id"]:
        await delete_messages([state["analise_message_id"]])
        state["analise_message_id"] = None

async def refresh_analise_message():
    now = datetime.now().timestamp()
    if now - state["last_analise_refresh"] < ANALISE_REFRESH_INTERVAL:
        return
    await delete_analise_message()
    mid = await send_to_channel(format_analise_text())
    if mid:
        state["analise_message_id"] = mid
        state["last_analise_refresh"] = now

# ───────────────────────────────────────────────
# API + HISTÓRICO
# ───────────────────────────────────────────────

async def fetch_api(session):
    try:
        async with session.get(API_URL, headers=HEADERS, timeout=12) as r:
            if r.status != 200:
                return None
            return await r.json()
    except Exception as e:
        logger.debug(f"Erro fetch API: {e}")
        return None

async def update_history_from_api(session):
    reset_placar_if_needed()
    data = await fetch_api(session)
    if not data:
        return

    try:
        if "data" in data:
            data = data["data"]
        rid = data.get("id")
        outcome_raw = (data.get("result") or {}).get("outcome")
        if not rid or not outcome_raw:
            return

        outcome = OUTCOME_MAP.get(outcome_raw)
        if not outcome:
            s = str(outcome_raw).lower()
            if "player" in s:
                outcome = "🔵"
            elif "banker" in s:
                outcome = "🔴"
            elif any(x in s for x in ["tie", "empate", "draw"]):
                outcome = "🟡"

        if outcome and state["last_round_id"] != rid:
            state["last_round_id"] = rid
            state["history"].append(outcome)
            if len(state["history"]) > 300:
                state["history"].pop(0)

            # Capturar scores
            result = data.get("result", {})
            ps = bs = None
            for side in ["player", "playerDice"]:
                d = result.get(side, {})
                for k in ("score", "sum", "total", "points"):
                    if k in d:
                        ps = d[k]
                        break
            for side in ["banker", "bankerDice"]:
                d = result.get(side, {})
                for k in ("score", "sum", "total", "points"):
                    if k in d:
                        bs = d[k]
                        break

            if ps is not None and bs is not None:
                state["player_score_last"] = ps
                state["banker_score_last"] = bs
                state["history_sums"].append((ps, bs))
                if len(state["history_sums"]) > 100:
                    state["history_sums"].pop(0)

            logger.info(f"Resultado: {outcome} | round {rid} | P:{ps} B:{bs}")

            if outcome == "🟡" and not state["waiting_for_result"]:
                state["total_empates"] += 1

    except Exception as e:
        logger.exception("Erro ao parsear API")

# ───────────────────────────────────────────────
# DETECÇÃO DE SINAL
# ───────────────────────────────────────────────

def detectar_melhor_sinal():
    h = state["history"]
    if len(h) < 4:
        return None, None, None

    votos = {"🔵": 0.0, "🔴": 0.0, "🟡": 0.0}
    ativados = []

    ps = state.get("player_score_last")
    bs = state.get("banker_score_last")

    for _, nome, cond, alvo, pts in PATTERNS:
        try:
            res = cond(h, ps, bs)
            if res is True:
                cor = alvo
            elif callable(alvo):
                cor = alvo(h, ps, bs)
                if cor not in ("🔵", "🔴", "🟡"):
                    continue
            else:
                continue

            votos[cor] += pts
            ativados.append(f"{nome} ({pts:.1f})")
        except:
            pass

    total = sum(votos.values())
    if total < MIN_SCORE_TO_SIGNAL:
        return None, None, None

    cor = max(votos, key=votos.get)
    confianca = votos[cor] / total * 100 if total > 0 else 0

    desc = " + ".join(ativados[:3])
    if len(ativados) > 3:
        desc += f" +{len(ativados)-3}"

    return f"{desc} ({confianca:.0f}%)", cor, total

# ───────────────────────────────────────────────
# PROCESSAMENTO DE RESULTADO
# ───────────────────────────────────────────────

async def process_round_result():
    if not state["waiting_for_result"] or not state["last_signal_color"]:
        return

    ultimo = state["history"][-1]
    alvo = state["last_signal_color"]

    # GREEN: acertou a cor OU empate
    if ultimo == alvo or ultimo == "🟡":
        state["total_greens"] += 1
        state["greens_seguidos"] += 1

        if state["martingale_count"] == 0:
            state["greens_sem_gale"] += 1
        elif state["martingale_count"] == 1:
            state["greens_gale_1"] += 1
        elif state["martingale_count"] == 2:
            state["greens_gale_2"] += 1

        extra = " (empate)" if ultimo == "🟡" else ""
        tipo_entrada = "Entrada principal" if state["martingale_count"] == 0 else f"Gale {state['martingale_count']}"

        await send_to_channel(
            f"✅ <b>GREEN</b> ✅\n"
            f"{tipo_entrada}{extra}\n"
        )

        p = state.get("player_score_last", "?")
        b = state.get("banker_score_last", "?")
        resultado_texto = f"💰 {alvo} | {p} • {b}"
        if ultimo == "🟡":
            resultado_texto += "  🟡 EMPATE (GREEN)"
        await send_to_channel(resultado_texto)

        await send_to_channel(format_placar())

        if state["greens_seguidos"] >= 3:
            await send_to_channel(f"🔥 {state['greens_seguidos']} greens seguidos! 🔥")

        await clear_gale_messages()

        state.update({
            "waiting_for_result": False,
            "last_signal_color": None,
            "martingale_count": 0,
            "entrada_message_id": None,
            "signal_round_id": None,
            "signal_cooldown": True,
            "signal_cooldown_end": datetime.now().timestamp() + COOLDOWN_AFTER_SIGNAL_SECONDS,
        })
        return

    # Perdeu → avança gale
    state["martingale_count"] += 1

    if state["martingale_count"] == 1:
        mid = await send_to_channel("🔴 <b>GALE 1</b> – mesma cor!")
        if mid:
            state["gale_message_ids"].append(mid)
        return

    if state["martingale_count"] == 2:
        mid = await send_to_channel("🔴 <b>GALE 2</b> – última tentativa!")
        if mid:
            state["gale_message_ids"].append(mid)
        return

    # Loss após gale 2
    state["greens_seguidos"] = 0
    state["total_losses"] += 1

    await send_to_channel("🟥 <b>LOSS</b> – gale 2 não entrou")
    await send_to_channel(format_placar())
    await clear_gale_messages()

    state.update({
        "waiting_for_result": False,
        "last_signal_color": None,
        "martingale_count": 0,
        "entrada_message_id": None,
        "signal_round_id": None,
        "signal_cooldown": True,
        "signal_cooldown_end": datetime.now().timestamp() + COOLDOWN_AFTER_SIGNAL_SECONDS + 10,
    })

# ───────────────────────────────────────────────
# ENVIO DE NOVO SINAL
# ───────────────────────────────────────────────

async def try_send_new_signal():
    if state["waiting_for_result"]:
        return

    now = datetime.now().timestamp()
    if state["signal_cooldown"] and now < state["signal_cooldown_end"]:
        return

    padrao, cor, score = detectar_melhor_sinal()
    if not cor:
        return

    if state["signal_round_id"] == state["last_round_id"]:
        return

    await delete_analise_message()
    await clear_gale_messages()

    text = (
        f"🎯 <b>SINAL CLEVER</b> 🎯\n"
        f"→ APOSTE: <b>{cor}</b>\n"
        f"Proteja o 🟡\n"
        f"<i>{padrao}</i>"
    )
    msg_id = await send_to_channel(text)

    if msg_id:
        state.update({
            "entrada_message_id": msg_id,
            "waiting_for_result": True,
            "last_signal_color": cor,
            "martingale_count": 0,
            "signal_round_id": state["last_round_id"],
            "signal_cooldown": True,
            "signal_cooldown_end": now + COOLDOWN_AFTER_SIGNAL_SECONDS,
        })
        logger.info(f"Sinal enviado → {cor} | {padrao}")

# ───────────────────────────────────────────────
# WORKERS
# ───────────────────────────────────────────────

async def api_worker():
    async with aiohttp.ClientSession() as session:
        while True:
            await update_history_from_api(session)

            if is_new_round():
                state["last_processed_round_id"] = state["last_round_id"]
                await process_round_result()

            await asyncio.sleep(API_POLL_INTERVAL)

async def scheduler_worker():
    await asyncio.sleep(4)
    while True:
        await try_send_new_signal()
        await refresh_analise_message()
        await asyncio.sleep(SIGNAL_CYCLE_INTERVAL)

async def main():
    logger.info("Bot iniciado – Empate conta como GREEN")
    await send_to_channel("🤖 Bot atualizado – <b>EMPATE = GREEN</b> (conta no placar)")
    await asyncio.gather(api_worker(), scheduler_worker())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Parado pelo usuário")
    except Exception as e:
        logger.critical("Erro fatal", exc_info=True)
