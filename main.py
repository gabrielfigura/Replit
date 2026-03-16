import os
import asyncio
import logging
import json
from typing import List, Optional, Dict, Any
from datetime import datetime
import pytz
from collections import Counter
import aiohttp
from telegram import Bot
from telegram.error import TelegramError
from dotenv import load_dotenv

load_dotenv()

# Configurações
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8163319902:AAHE9LZ984JCIc-Lezl4WXR2FsGHPEFTxRQ")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "-1003882537733")

API_URL = "https://api.signals-house.com/validate/results?tableId=2&lastResult=13343863"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json',
    'Accept-Language': 'en-US,en;q=0.9',
}

ANGOLA_TZ = pytz.timezone('Africa/Luanda')
STATE_FILE = "bot_state.json"

OUTCOME_MAP = {
    "PlayerWon": "🔵",
    "BankerWon": "🔴",
    "Tie": "🟡",
    "Player": "🔵",
    "Banker": "🔴",
    "🔵": "🔵",
    "🔴": "🔴",
    "🟡": "🟡",
}

API_POLL_INTERVAL = 4.2
SIGNAL_COOLDOWN_DURATION = 9

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-5s | %(message)s'
)

logger = logging.getLogger("BacBoBot")
bot = Bot(token=TELEGRAM_BOT_TOKEN)

state: Dict[str, Any] = {
    "history": [],
    "history_times": [],
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
    "last_signal_pattern": None,
    "last_signal_sequence": None,
    "last_signal_round_id": None,
    "signal_cooldown_until": 0.0,
    "analise_message_id": None,
    "last_analise_refresh": 0.0,
    "last_result_round_id": None,
    "player_score_last": None,
    "banker_score_last": None,
    "new_result_added": False,
}

# ────────────────────────────────────────
# PERSISTÊNCIA DO PLACAR (NUNCA ZERA)
# ────────────────────────────────────────

PERSISTENT_KEYS = [
    "total_greens", "greens_sem_gale", "greens_gale_1", "greens_gale_2",
    "total_empates", "total_losses", "greens_seguidos", "last_round_id"
]

def save_state():
    """Salva o placar em arquivo JSON para nunca perder entre reinícios."""
    try:
        to_save = {k: state[k] for k in PERSISTENT_KEYS}
        with open(STATE_FILE, "w") as f:
            json.dump(to_save, f, indent=2)
        logger.info(f"Placar salvo: 🟢{state['total_greens']} 🔴{state['total_losses']}")
    except Exception as e:
        logger.error(f"Erro ao salvar placar: {e}")

def load_state():
    """Carrega o placar salvo anteriormente. Nunca zera."""
    try:
        with open(STATE_FILE, "r") as f:
            saved = json.load(f)
            state.update(saved)
            logger.info(f"Placar carregado: 🟢{state['total_greens']} 🔴{state['total_losses']} | Seguidos: {state['greens_seguidos']}")
    except FileNotFoundError:
        logger.info("Nenhum placar anterior encontrado. Começando do zero.")
    except Exception as e:
        logger.error(f"Erro ao carregar placar: {e}")


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
        logger.error(f"Erro ao enviar texto: {e}")
        return None


async def send_error_to_channel(error_msg: str):
    timestamp = datetime.now(ANGOLA_TZ).strftime("%Y-%m-%d %H:%M:%S")
    text = f"⚠️ <b>ERRO DETECTADO</b> ⚠️\n<code>{timestamp}</code>\n\n{error_msg}"
    await send_to_channel(text)


async def delete_messages(message_ids: List[int]):
    if not message_ids:
        return
    for mid in message_ids[:]:
        try:
            await bot.delete_message(TELEGRAM_CHANNEL_ID, mid)
        except:
            pass


def calcular_acertividade() -> str:
    total = state["total_greens"] + state["total_losses"]
    return "0.00%" if total == 0 else f"{(state['total_greens'] / total * 100):.2f}%"


def format_placar() -> str:
    acert = calcular_acertividade()
    return (
        f"📊 <b>Histórico Total</b> 🟢 {state['total_greens']} 🔴 {state['total_losses']}\n"
        f"✅ Assertividade {acert}\n"
        f"🏆 {state['greens_seguidos']} Greens seguidos"
    )


def format_analise_text() -> str:
    return "🎲 <b>ANALISANDO...</b> 🎲\n<i>Aguarde sinal</i>"


async def refresh_analise_message():
    await delete_analise_message()
    msg_id = await send_to_channel(format_analise_text())
    if msg_id:
        state["analise_message_id"] = msg_id


async def delete_analise_message():
    if state["analise_message_id"] is not None:
        await delete_messages([state["analise_message_id"]])
        state["analise_message_id"] = None


async def fetch_api(session: aiohttp.ClientSession) -> Optional[Dict]:
    try:
        async with session.get(API_URL, headers=HEADERS, timeout=7) as resp:
            if resp.status == 200:
                return await resp.json()
            return None
    except:
        return None


def calcular_intervalo_medio() -> float:
    """Calcula o intervalo médio entre rodadas baseado nos últimos resultados."""
    times = state.get("history_times", [])
    if len(times) < 3:
        return 33.0  # fallback ~33 segundos

    intervals = []
    for i in range(1, min(8, len(times))):
        diff = (times[i - 1] - times[i]).total_seconds()
        if 20 < diff < 60:
            intervals.append(diff)

    if not intervals:
        return 33.0

    return sum(intervals) / len(intervals)


async def update_history_from_api(session):
    # SEM reset de placar — nunca zera!
    data = await fetch_api(session)
    if not data:
        return

    try:
        items = data.get("data", [])
        if isinstance(items, list) and len(items) > 0:
            latest = items[0]
            round_id = latest.get("id")
            if not round_id:
                return

            outcome_raw = latest.get("result")
            if not outcome_raw:
                return

            score = latest.get("score")
            created_at_str = latest.get("createdAt")

            outcome = OUTCOME_MAP.get(outcome_raw)
            if not outcome:
                s = str(outcome_raw or "").lower()
                if "player" in s: outcome = "🔵"
                elif "banker" in s: outcome = "🔴"
                elif any(x in s for x in ["tie", "empate", "draw"]): outcome = "🟡"

            if outcome and state["last_round_id"] != round_id:
                state["last_round_id"] = round_id
                state["history"].append(outcome)
                state["player_score_last"] = None
                state["banker_score_last"] = None

                # Guardar timestamp para calcular intervalo
                if created_at_str:
                    try:
                        dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                        state["history_times"].insert(0, dt)
                        if len(state["history_times"]) > 20:
                            state["history_times"].pop()
                    except:
                        pass

                if len(state["history"]) > 200:
                    state["history"].pop(0)
                logger.info(f"Resultado novo: {outcome} (round {round_id}, score={score})")
                state["new_result_added"] = True
                state["signal_cooldown_until"] = datetime.now().timestamp() + 1.5

        elif isinstance(items, dict):
            round_id = items.get("id")
            if not round_id:
                return

            outcome_raw = (items.get("result") or {}).get("outcome") if isinstance(items.get("result"), dict) else items.get("result")
            if not outcome_raw:
                return

            player_dice = banker_dice = None
            if isinstance(items.get("result"), dict):
                result = items.get("result") or {}
                pl = result.get("player") or result.get("playerDice") or {}
                bk = result.get("banker") or result.get("bankerDice") or {}
                for k in ("score", "sum", "total", "points"):
                    if k in pl: player_dice = pl[k]
                    if k in bk: banker_dice = bk[k]

            outcome = OUTCOME_MAP.get(outcome_raw)
            if not outcome:
                s = str(outcome_raw or "").lower()
                if "player" in s: outcome = "🔵"
                elif "banker" in s: outcome = "🔴"
                elif any(x in s for x in ["tie", "empate", "draw"]): outcome = "🟡"

            if outcome and state["last_round_id"] != round_id:
                state["last_round_id"] = round_id
                state["history"].append(outcome)
                if player_dice is not None and banker_dice is not None:
                    state["player_score_last"] = player_dice
                    state["banker_score_last"] = banker_dice
                else:
                    state["player_score_last"] = None
                    state["banker_score_last"] = None
                if len(state["history"]) > 200:
                    state["history"].pop(0)
                logger.info(f"Resultado novo: {outcome} (round {round_id})")
                state["new_result_added"] = True
                state["signal_cooldown_until"] = datetime.now().timestamp() + 1.5

    except Exception as e:
        logger.debug(f"Erro processando API: {e}")


# ────────────────────────────────────────
# ESTRATÉGIAS
# ────────────────────────────────────────

def oposto(cor: str) -> str:
    return "🔵" if cor == "🔴" else "🔴"


def estrategia_maioria_recente(hist: List[str]):
    if len(hist) < 3:
        return None
    window = hist[-min(4, len(hist)):]
    cnt = Counter(x for x in window if x in ("🔵", "🔴"))
    if not cnt:
        return None
    cor, qtd = cnt.most_common(1)[0]
    if qtd >= 3 or qtd >= len(window) - 1:
        return ("Maioria Recente", cor)
    return None


def estrategia_repeticao(hist: List[str]):
    if len(hist) >= 3 and hist[-1] == hist[-2] == hist[-3] and hist[-1] in ("🔵", "🔴"):
        return ("3x repetição → reversão", oposto(hist[-1]))
    if len(hist) >= 2 and hist[-2] == hist[-1] and hist[-1] in ("🔵", "🔴"):
        return ("2x repetição", hist[-1])
    return None


def estrategia_alternancia(hist: List[str]):
    if len(hist) >= 4:
        last = hist[-4:]
        if all(x in ("🔵", "🔴") for x in last) and last[0] == last[2] and last[1] == last[3] and last[0] != last[1]:
            return ("Alternância ABAB", oposto(last[-1]))
    return None


def estrategia_paridade(player_score, banker_score):
    if player_score is None or banker_score is None:
        return None
    try:
        ps = int(player_score)
        bs = int(banker_score)
        if ps > bs:
            return ("Paridade", "🔵")
        if bs > ps:
            return ("Paridade", "🔴")
    except:
        pass
    return None


def gerar_sinal_estrategia(history: List[str], player_score=None, banker_score=None):
    if len(history) < 3:
        return None, None

    res = estrategia_maioria_recente(history)
    if res:
        return res

    votos = {"🔵": 0.0, "🔴": 0.0}
    melhor_nome = None

    for func, peso in [
        (estrategia_repeticao, 2.5),
        (estrategia_alternancia, 2.0),
    ]:
        res = func(history)
        if res:
            nome, cor = res
            votos[cor] += peso
            if melhor_nome is None:
                melhor_nome = nome

    res_par = estrategia_paridade(player_score, banker_score)
    if res_par:
        nome_par, cor_par = res_par
        votos[cor_par] += 1.5
        if melhor_nome is None:
            melhor_nome = nome_par

    total = votos["🔵"] + votos["🔴"]
    diff = abs(votos["🔵"] - votos["🔴"])

    if total >= 2.0 and diff >= 0.8:
        cor = "🔵" if votos["🔵"] > votos["🔴"] else "🔴"
        nome = melhor_nome or "Sinal Rápido"
        return (nome, cor)

    return None, None


def main_entry_text(color: str, round_id=None) -> str:
    round_info = f"\n<code>Round: #{round_id}</code>" if round_id else ""
    return (
        f"🎲 <b>ENTRADA CONFIRMADA</b> 🎲\n"
        f"APOSTA NA COR: {color}\n"
        f"PROTEJA O TIE 🟡{round_info}"
    )


async def send_gale_warning(level: int):
    if level not in (1, 2):
        return
    text = f"🔄 <b>GALE {level}</b> 🔄\nContinuar na mesma cor!"
    msg_id = await send_to_channel(text)
    if msg_id:
        state["martingale_message_ids"].append(msg_id)


async def clear_gale_messages():
    await delete_messages(state["martingale_message_ids"])
    state["martingale_message_ids"] = []


async def resolve_after_result():
    if not state.get("waiting_for_result") or not state.get("last_signal_color"):
        return
    if state["last_result_round_id"] == state["last_round_id"]:
        return
    if not state["history"]:
        return
    if state["last_signal_round_id"] >= state["last_round_id"]:
        return

    last_outcome = state["history"][-1]
    state["last_result_round_id"] = state["last_round_id"]
    target = state["last_signal_color"]
    acertou = last_outcome == target
    is_tie = last_outcome == "🟡"

    if acertou or is_tie:
        state["total_greens"] += 1
        state["greens_seguidos"] += 1
        if state["martingale_count"] == 0: state["greens_sem_gale"] += 1
        elif state["martingale_count"] == 1: state["greens_gale_1"] += 1
        elif state["martingale_count"] == 2: state["greens_gale_2"] += 1

        green_text = (
            "✅GREEN✅\n"
            "🤖MAIS FOCO E MENOS GANÂNCIA🤖"
        )
        await send_to_channel(green_text)
        await send_to_channel(format_placar())
        await clear_gale_messages()

        # Salvar placar após green (NUNCA ZERA)
        save_state()

        state.update({
            "waiting_for_result": False,
            "last_signal_color": None,
            "martingale_count": 0,
            "entrada_message_id": None,
            "last_signal_pattern": None,
            "last_signal_sequence": None,
            "last_signal_round_id": None,
            "signal_cooldown_until": datetime.now().timestamp() + SIGNAL_COOLDOWN_DURATION
        })
        return

    state["martingale_count"] += 1
    if state["martingale_count"] == 1:
        await send_gale_warning(1)
    elif state["martingale_count"] == 2:
        await send_gale_warning(2)

    if state["martingale_count"] >= 3:
        state["greens_seguidos"] = 0
        state["total_losses"] += 1
        await send_to_channel("🟥 <b>LOSS</b> 🟥")
        await send_to_channel(format_placar())
        await clear_gale_messages()

        # Salvar placar após loss (NUNCA ZERA)
        save_state()

        state.update({
            "waiting_for_result": False,
            "last_signal_color": None,
            "martingale_count": 0,
            "entrada_message_id": None,
            "last_signal_pattern": None,
            "last_signal_sequence": None,
            "last_signal_round_id": None,
            "signal_cooldown_until": datetime.now().timestamp() + SIGNAL_COOLDOWN_DURATION
        })

    await refresh_analise_message()


async def try_send_signal():
    now = datetime.now().timestamp()
    if state["waiting_for_result"]:
        await delete_analise_message()
        return
    if now < state["signal_cooldown_until"]:
        return
    if len(state["history"]) < 3:
        return
    if not state["new_result_added"]:
        return

    state["new_result_added"] = False

    padrao, cor = gerar_sinal_estrategia(
        state["history"],
        state.get("player_score_last"),
        state.get("banker_score_last")
    )

    if not cor:
        await refresh_analise_message()
        return

    seq = "".join(state["history"][-6:])
    if state["last_signal_pattern"] == padrao and state["last_signal_sequence"] == seq:
        await refresh_analise_message()
        return

    await delete_analise_message()
    state["martingale_message_ids"] = []

    # ────────────────────────────────────────
    # ENVIAR SINAL 7 SEGUNDOS ANTES DA RODADA
    # ────────────────────────────────────────
    avg_interval = calcular_intervalo_medio()
    times = state.get("history_times", [])

    if len(times) >= 2:
        elapsed = (datetime.now(pytz.utc) - times[0]).total_seconds()
        wait_time = avg_interval - elapsed - 7  # 7 segundos antes

        if 0 < wait_time < 45:
            # Enviar aviso de preparação
            prep_msg_id = await send_to_channel(
                "⏳ <b>PREPARANDO ENTRADA...</b>\n"
                "<i>Sinal em breve, fique atento!</i>"
            )
            logger.info(f"Aguardando {wait_time:.1f}s para enviar sinal 7s antes da rodada (intervalo médio: {avg_interval:.1f}s)")
            await asyncio.sleep(wait_time)

            # Apagar mensagem de preparação
            if prep_msg_id:
                await delete_messages([prep_msg_id])
        elif wait_time <= 0:
            # Já está dentro da janela, enviar imediatamente
            logger.info("Janela de 7s já passou, enviando sinal imediatamente")

    msg_id = await send_to_channel(main_entry_text(cor, state.get("last_round_id")))
    if msg_id:
        state["entrada_message_id"] = msg_id
        state["waiting_for_result"] = True
        state["last_signal_color"] = cor
        state["martingale_count"] = 0
        state["last_signal_pattern"] = padrao
        state["last_signal_sequence"] = seq
        state["last_signal_round_id"] = state["last_round_id"]
        state["signal_cooldown_until"] = now + SIGNAL_COOLDOWN_DURATION
        logger.info(f"Sinal enviado → {cor} ({padrao})")


async def api_worker():
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                await update_history_from_api(session)
                await asyncio.sleep(0.6)
                await resolve_after_result()
                await try_send_signal()
            except Exception as e:
                logger.debug(f"Erro loop principal: {e}")
            await asyncio.sleep(API_POLL_INTERVAL)


async def main():
    # Carregar placar anterior (NUNCA ZERA)
    load_state()

    logger.info("Bot iniciado...")
    placar_info = f"🟢{state['total_greens']} 🔴{state['total_losses']}"
    await send_to_channel(
        f"🤖 <b>BOT INICIADO</b> 🤖\n"
        f"📊 Histórico Total: {placar_info}"
    )
    await api_worker()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot parado pelo usuário")
        save_state()
    except Exception as e:
        logger.critical("Erro fatal", exc_info=True)
        save_state()
