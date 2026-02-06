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
SIGNAL_CYCLE_INTERVAL  = 5
ANALISE_REFRESH_INTERVAL = 15

MIN_SCORE_TO_SIGNAL = 12.0          # Ajusta: mais alto = menos sinais, maior qualidade

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)-5s | %(message)s')
logger = logging.getLogger("BacBoMultiPatterns")
bot = Bot(token=TELEGRAM_BOT_TOKEN)

state: Dict[str, Any] = {
    "history": [],                  # lista de "🔵","🔴","🟡"
    "history_sums": [],             # lista de tuplos (player_sum, banker_sum)
    "last_round_id": None,
    "waiting_for_result": False,
    "last_signal_color": None,
    "martingale_count": 0,
    "entrada_message_id": None,
    "martingale_message_ids": [],
    "greens_seguidos": 0,
    "total_greens": 0,
    "greens_sem_gale": 0,
    "greens_gale_1": 0,
    "greens_gale_2": 0,
    "total_empates": 0,
    "total_losses": 0,
    "last_signal_round_id": None,
    "signal_cooldown": False,
    "analise_message_id": None,
    "last_reset_date": None,
    "last_analise_refresh": 0.0,
    "last_result_round_id": None,
    "player_score_last": None,
    "banker_score_last": None,
}

# ───────────────────────────────────────────────
# DEFINIÇÃO DOS PADRÕES (baseado na tua lista de 50)
# ───────────────────────────────────────────────

def count_last_consecutive(hist: List[str], cor: str) -> int:
    count = 0
    for i in range(len(hist)-1, -1, -1):
        if hist[i] == cor:
            count += 1
        elif hist[i] != "🟡":
            break
    return count

PATTERNS = [
    # id, nome, função(h, ps, bs) → True/False ou cor direta, pontos(assertividade/10)
    (1,  "Triplo Jogador",          lambda h,ps,bs: count_last_consecutive(h,"🔵") >= 3,                 "🔴",  8.8),
    (2,  "Intercalado Clássico",    lambda h,ps,bs: len(h)>=4 and h[-4:] == ["🔵","🔴","🔵","🔴"],      "🔴",  8.5),
    (4,  "Recuperação do Empate",   lambda h,ps,bs: len(h)>=2 and h[-1]=="🟡" and h[-2] in ["🔵","🔴"], lambda h,ps,bs: h[-2], 8.2),
    (6,  "Padrão 2-2 Quebrado",     lambda h,ps,bs: len(h)>=4 and h[-4:] == ["🔵","🔵","🔴","🔴"],      "🔴",  8.7),  # ou inverter para 🔵 dependendo da tua preferência
    (11, "Padrão 3-1-3",            lambda h,ps,bs: len(h)>=7 and h[-7:-4]==["🔵"]*3 and h[-4]=="🔴" and h[-3:]==["🔵"]*3, "🔴", 8.9),
    (13, "Onda Alternada PBx3",     lambda h,ps,bs: len(h)>=6 and h[-6:]==["🔵","🔴"]*3,                 "🔵",  8.6),
    (16, "Quebra de Coluna Px4",    lambda h,ps,bs: count_last_consecutive(h,"🔵") >= 4,                 "🔴",  8.8),
    (23, "Salto de Tigre",          lambda h,ps,bs: len(h)>=3 and h[-3:]==["🔵","🔴","🔵"],              "🔵",  8.4),
    (24, "Muralha de Banker Bx5",   lambda h,ps,bs: count_last_consecutive(h,"🔴") >= 5,                 "🔵",  8.1),
    (27, "Ziguezague Curto",        lambda h,ps,bs: len(h)>=4 and h[-4:]==["🔵","🔴","🔵","🔴"],         "🔵",  8.3),
    (28, "Ziguezague Longo",        lambda h,ps,bs: len(h)>=6 and h[-6:]==["🔵","🔴"]*3,                 "🔴",  8.7),
    (37, "Bloco de 4 PPPP → B",     lambda h,ps,bs: count_last_consecutive(h,"🔵") >= 4,                 "🔴",  8.5),

    # Padrões com soma (necessitam history_sums ou last sums)
    (3,  "Soma Máxima P12+", lambda h,ps,bs:
        len(state["history_sums"])>=2 and
        state["history_sums"][-1][0] >=12 and state["history_sums"][-2][0] >=12, "🔴", 9.2),

    (7,  "Soma Baixa <5 x3", lambda h,ps,bs:
        len(state["history_sums"])>=3 and
        all((p+b)<5 for p,b in state["history_sums"][-3:]), "🔵", 9.0),

    (12, "Soma 7 Mágica Banker", lambda h,ps,bs: bs == 7, "🔴", 8.1),

    (25, "Soma Central B 8-9", lambda h,ps,bs: bs in (8,9), "🔴", 8.6),

    # TODO: implementar os restantes que precisem de mais estado (ex: últimos 10/20, frequência, diff exata, dados individuais, etc.)
    # (5,  "Diferença 1 ponto Banker",     ... )
    # (9,  "Anti-Empate 5",                ... )
    # (14, "Diferença 6+",                 ... )
    # (15, "Ciclo de 10 <30%",             ... )
    # (19, "Vácuo Banker 4",               ... )
    # etc.
]

async def send_to_channel(text: str, parse_mode="HTML") -> Optional[int]:
    try:
        msg = await bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=text, parse_mode=parse_mode, disable_web_page_preview=True)
        return msg.message_id
    except Exception as e:
        logger.error(f"Erro envio Telegram: {e}")
        return None

async def send_error_to_channel(error_msg: str):
    ts = datetime.now(ANGOLA_TZ).strftime("%Y-%m-%d %H:%M:%S")
    await send_to_channel(f"⚠️ <b>ERRO</b> ⚠️\n<code>{ts}</code>\n\n{error_msg}")

async def delete_messages(message_ids: List[int]):
    for mid in message_ids[:]:
        try: await bot.delete_message(TELEGRAM_CHANNEL_ID, mid)
        except: pass

def should_reset_placar() -> bool:
    now = datetime.now(ANGOLA_TZ)
    if state["last_reset_date"] != now.date() or state["total_losses"] >= 10:
        state["last_reset_date"] = now.date()
        return True
    return False

def reset_placar_if_needed():
    if should_reset_placar():
        for k in ["total_greens","greens_sem_gale","greens_gale_1","greens_gale_2",
                  "total_empates","total_losses","greens_seguidos"]:
            state[k] = 0
        logger.info("Placar resetado")

def calcular_acertividade() -> str:
    total = state["total_greens"] + state["total_losses"]
    return "—" if total == 0 else f"{state['total_greens']/total*100:.1f}%"

def format_placar() -> str:
    return (
        "🏆 <b>RESUMO</b> 🏆\n"
        f"✅ Sem gale: <b>{state['greens_sem_gale']}</b>\n"
        f"🔄 Gale 1: <b>{state['greens_gale_1']}</b>\n"
        f"🔄 Gale 2: <b>{state['greens_gale_2']}</b>\n"
        f"🤝 Empates: <b>{state['total_empates']}</b>\n"
        f"⛔ Losses: <b>{state['total_losses']}</b>\n"
        f"────────────────────\n"
        f"🎯 Greens: <b>{state['total_greens']}</b>  |  Acertividade: <b>{calcular_acertividade()}</b>"
    )

def format_analise_text() -> str:
    return "🎲 <b>ANALISANDO PADRÕES...</b> 🎲\n\n<i>Aguarde o próximo sinal</i>"

async def refresh_analise_message():
    now = datetime.now().timestamp()
    if now - state["last_analise_refresh"] < ANALISE_REFRESH_INTERVAL:
        return
    await delete_messages([state["analise_message_id"]]) if state["analise_message_id"] else None
    mid = await send_to_channel(format_analise_text())
    if mid:
        state["analise_message_id"] = mid
        state["last_analise_refresh"] = now

async def delete_analise_message():
    if state["analise_message_id"]:
        await delete_messages([state["analise_message_id"]])
        state["analise_message_id"] = None

async def fetch_api(session):
    try:
        async with session.get(API_URL, headers=HEADERS, timeout=12) as r:
            if r.status != 200: return None
            return await r.json()
    except:
        return None

async def update_history_from_api(session):
    reset_placar_if_needed()
    data = await fetch_api(session)
    if not data: return

    try:
        if "data" in data: data = data["data"]
        rid = data.get("id")
        outcome_raw = (data.get("result") or {}).get("outcome")
        if not rid or not outcome_raw: return

        outcome = OUTCOME_MAP.get(outcome_raw)
        if not outcome:
            s = str(outcome_raw).lower()
            if "player" in s: outcome = "🔵"
            elif "banker" in s: outcome = "🔴"
            elif any(x in s for x in ["tie","empate","draw"]): outcome = "🟡"

        if outcome and state["last_round_id"] != rid:
            state["last_round_id"] = rid
            state["history"].append(outcome)
            if len(state["history"]) > 300: state["history"].pop(0)

            # Tentar capturar somas
            result = data.get("result", {})
            ps = None
            bs = None
            for side in ["player", "playerDice"]:
                d = result.get(side, {})
                for k in ("score","sum","total","points"):
                    if k in d: ps = d[k]; break
            for side in ["banker", "bankerDice"]:
                d = result.get(side, {})
                for k in ("score","sum","total","points"):
                    if k in d: bs = d[k]; break

            if ps is not None and bs is not None:
                state["player_score_last"] = ps
                state["banker_score_last"] = bs
                state["history_sums"].append((ps, bs))
                if len(state["history_sums"]) > 100: state["history_sums"].pop(0)

            if outcome == "🟡": state["total_empates"] += 1

            logger.info(f"Resultado: {outcome} | round {rid}")
            state["signal_cooldown"] = False

    except Exception as e:
        logger.exception("Erro parse API")

def detectar_melhor_sinal():
    h = state["history"]
    if len(h) < 4: return None, None, None

    votos = {"🔵": 0.0, "🔴": 0.0}
    ativados = []

    ps = state.get("player_score_last")
    bs = state.get("banker_score_last")

    for pid, nome, cond, alvo, pts in PATTERNS:
        try:
            res = cond(h, ps, bs)
            if res is True:
                cor = alvo
            elif callable(alvo):
                cor = alvo(h, ps, bs)
                if cor not in ("🔵","🔴"): continue
            else:
                continue

            votos[cor] += pts
            ativados.append(f"{nome} ({pts:.1f})")

        except:
            pass

    total = sum(votos.values())
    if total < MIN_SCORE_TO_SIGNAL: return None, None, None

    cor = "🔵" if votos["🔵"] > votos["🔴"] else "🔴"
    confianca = max(votos.values()) / total * 100

    desc = " + ".join(ativados[:3])
    if len(ativados) > 3: desc += f" +{len(ativados)-3}"

    return f"{desc} ({confianca:.0f}%)", cor, total

def main_entry_text(padrao: str, cor: str) -> str:
    return (
        f"🎲 <b>ENTRADA – {cor}</b> 🎲\n\n"
        f"{cor}   ←   {padrao}\n\n"
        f"Proteja o Tie 🟡\n"
        f"<i>Gestão responsável</i>"
    )

def green_text():
    p = state.get("player_score_last", "?")
    b = state.get("banker_score_last", "?")
    return f"💰 GREEN 💰\n🔵 {p}  •  🔴 {b}"

async def send_gale_warning(level: int):
    if level not in (1,2): return
    mid = await send_to_channel(f"🔄 <b>GALE {level}</b> 🔄\nMesma cor!")
    if mid: state["martingale_message_ids"].append(mid)

async def clear_gale_messages():
    await delete_messages(state["martingale_message_ids"])
    state["martingale_message_ids"] = []

async def resolve_after_result():
    if not state["waiting_for_result"] or not state["last_signal_color"]: return
    if state["last_result_round_id"] == state["last_round_id"]: return

    state["last_result_round_id"] = state["last_round_id"]
    ultimo = state["history"][-1]
    alvo = state["last_signal_color"]
    acertou = ultimo == alvo
    tie = ultimo == "🟡"

    if acertou or tie:
        state["total_greens"] += 1
        state["greens_seguidos"] += 1
        if state["martingale_count"] == 0: state["greens_sem_gale"] += 1
        elif state["martingale_count"] == 1: state["greens_gale_1"] += 1
        elif state["martingale_count"] == 2: state["greens_gale_2"] += 1

        await send_to_channel(green_text())
        await send_to_channel(format_placar())
        await send_to_channel(f"🔥 {state['greens_seguidos']} greens seguidos 🔥")

        await clear_gale_messages()

        state.update({
            "waiting_for_result": False, "last_signal_color": None,
            "martingale_count": 0, "entrada_message_id": None,
            "last_signal_round_id": None, "signal_cooldown": True
        })
        return

    state["martingale_count"] += 1
    if state["martingale_count"] == 1: await send_gale_warning(1)
    elif state["martingale_count"] == 2: await send_gale_warning(2)

    if state["martingale_count"] >= 3:
        state["greens_seguidos"] = 0
        state["total_losses"] += 1
        await send_to_channel("🟥 <b>LOSS</b> 🟥")
        await send_to_channel(format_placar())
        await clear_gale_messages()

        state.update({
            "waiting_for_result": False, "last_signal_color": None,
            "martingale_count": 0, "entrada_message_id": None,
            "last_signal_round_id": None, "signal_cooldown": True
        })
        reset_placar_if_needed()

    await refresh_analise_message()

async def try_send_signal():
    if state["waiting_for_result"] or state["signal_cooldown"]: 
        await refresh_analise_message()
        return

    padrao, cor, score = detectar_melhor_sinal()
    if not cor: 
        await refresh_analise_message()
        return

    if state["last_signal_round_id"] == state["last_round_id"]: return

    await delete_analise_message()
    state["martingale_message_ids"] = []

    msg_id = await send_to_channel(main_entry_text(padrao, cor))
    if msg_id:
        state.update({
            "entrada_message_id": msg_id,
            "waiting_for_result": True,
            "last_signal_color": cor,
            "martingale_count": 0,
            "last_signal_round_id": state["last_round_id"],
            "signal_cooldown": True,
        })
        logger.info(f"Sinal: {cor} | {padrao} | score {score:.1f}")

async def api_worker():
    async with aiohttp.ClientSession() as s:
        while True:
            await update_history_from_api(s)
            await resolve_after_result()
            await asyncio.sleep(API_POLL_INTERVAL)

async def scheduler_worker():
    await asyncio.sleep(3)
    while True:
        await refresh_analise_message()
        await try_send_signal()
        await asyncio.sleep(SIGNAL_CYCLE_INTERVAL)

async def main():
    logger.info("Bot Multi-Padrões iniciado...")
    await send_to_channel("🤖 Bot iniciado – procurando padrões...")
    await asyncio.gather(api_worker(), scheduler_worker())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Parado pelo usuário")
    except Exception as e:
        logger.critical("Erro fatal", exc_info=True)
