import os
import asyncio
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
import pytz

import aiohttp
from telegram import Bot
from telegram.error import TelegramError
from dotenv import load_dotenv

load_dotenv()

# Configurações
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7703975421:AAG-CG5Who2xs4NlevJqB5TNvjjzeUEDz8o")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "-1002859771274")

API_URL = "https://api-cs.casino.org/svc-evolution-game-events/api/bacbo/latest"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json',
    'Accept-Language': 'en-US,en;q=0.9',
}

ANGOLA_TZ = pytz.timezone('Africa/Luanda')

OUTCOME_MAP = {
    "PlayerWon": "🔵",
    "BankerWon": "🔴",
    "Tie": "🟡",
    "🔵": "🔵",
    "🔴": "🔴",
    "🟡": "🟡",
}

# teus padrões (mantive exatamente iguais)
PADROES = [ ... ]  # ← copia aqui a tua lista completa de PADROES (não alterei)

API_POLL_INTERVAL = 3
SIGNAL_CYCLE_INTERVAL = 5
ANALISE_REFRESH_INTERVAL = 15

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-5s | %(message)s'
)
logger = logging.getLogger("BacBoBot")

bot = Bot(token=TELEGRAM_BOT_TOKEN)

# Estado global
state: Dict[str, Any] = {
    "history": [],
    "last_round_id": None,
    "waiting_for_result": False,
    "last_signal_color": None,
    "martingale_count": 0,
    "entrada_message_id": None,
    "martingale_message_ids": [],
    "greens_seguidos": 0,
    "total_greens": 0,
    "total_empates": 0,
    "total_losses": 0,
    "last_signal_pattern_id": None,
    "last_signal_sequence": None,
    "last_signal_round_id": None,
    "signal_cooldown": False,
    "analise_message_id": None,
    "last_reset_date": None,
    "last_analise_refresh": 0.0,
    "last_result_round_id": None,
}


async def send_to_channel(text: str, parse_mode="HTML") -> Optional[int]:
    try:
        msg = await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=text,
            parse_mode=parse_mode,
            disable_web_page_preview=True
        )
        return msg.message_id
    except TelegramError as te:
        logger.error(f"Telegram Error: {te}")
        return None
    except Exception as e:
        logger.exception("Erro ao enviar mensagem")
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


def should_reset_placar() -> bool:
    # Reset diário
    now = datetime.now(ANGOLA_TZ)
    current_date = now.date()
    if state["last_reset_date"] is None or state["last_reset_date"] != current_date:
        state["last_reset_date"] = current_date
        return True
    
    # Reset extra quando losses ≥ 10
    if state["total_losses"] >= 10:
        return True
    
    return False


def reset_placar_if_needed():
    if should_reset_placar():
        state["total_greens"] = 0
        state["total_empates"] = 0
        state["total_losses"] = 0
        state["greens_seguidos"] = 0
        logger.info("🔄 Placar resetado (diário ou por 10 losses)")
        # Pode mandar mensagem opcional se quiseres:
        # asyncio.create_task(send_to_channel("🔄 <b>PLACAR ZERADO</b> (10 losses ou novo dia)"))


def calcular_acertividade() -> str:
    total_decisoes = state["total_greens"] + state["total_losses"]
    if total_decisoes == 0:
        return "—"
    perc = (state["total_greens"] / total_decisoes) * 100
    return f"{perc:.1f}%"


def format_placar() -> str:
    acert = calcular_acertividade()
    return (
        "🏆 <b>PLACAR DO DIA</b> 🏆\n"
        f"✅ GREENS: <b>{state['total_greens']}</b>\n"
        f"🤝 EMPATES: {state['total_empates']}\n"
        f"⛔ LOSS: <b>{state['total_losses']}</b>\n"
        f"🎯 ACERTIVIDADE: <b>{acert}</b>"
    )


def format_analise_text() -> str:
    return (
        "🔍 <b>ANALISANDO...</b> 🔍\n\n"
        "<i>Aguarde o próximo sinal</i>\n\n"
        f"{format_placar()}"
    )


async def refresh_analise_message():
    now = datetime.now().timestamp()
    if (now - state["last_analise_refresh"]) < ANALISE_REFRESH_INTERVAL:
        return

    await delete_analise_message()
    msg_id = await send_to_channel(format_analise_text())
    if msg_id:
        state["analise_message_id"] = msg_id
        state["last_analise_refresh"] = now


async def delete_analise_message():
    if state["analise_message_id"] is not None:
        await delete_messages([state["analise_message_id"]])
        state["analise_message_id"] = None


# ... (mantém fetch_api, update_history_from_api, history_ends_with, find_matching_pattern iguais)


def main_entry_text(color: str) -> str:
    cor_nome = "AZUL" if color == "🔵" else "VERMELHO"
    emoji = color
    return (
        f"💡 <b>CLEVER ANALISOU</b> 💡\n"
        f"🧠 APOSTA EM: <b>{emoji} {cor_nome}</b>\n"
        f"🛡️ Proteja o TIE <b>🟡</b>\n"
        f"<b>FAZER ATÉ 1 GALE</b>\n"
        f"🤑 <b>VAI ENTRAR DINHEIRO</b> 🤑\n\n"
        f"{format_placar()}"
    )


def martingale_text(color: str) -> str:
    return (
        f"➡️ <b>Vamos para o 1º GALE</b>\n"
        f"🎯 Alvo: {color}\n"
        f"{format_placar()}"
    )


def green_text(greens: int) -> str:
    if greens <= 1:
        return (
            f"🤡 <b>ENTROU DINHEIRO</b> 🤡\n"
            f"🎲 <b>CLEVER_M</b> 🎲\n\n"
            f"{format_placar()}"
        )
    else:
        # Letras grandes (negrito + maiúsculas) + nome
        return (
            f"<b>ESTAMOS COM {greens} VITÓRIAS EM SEGUIDAS COM CLEVER_M 🔥</b>\n"
            f"<b>PAGA BLACK G1</b>\n\n"
            f"{format_placar()}"
        )


async def resolve_after_result():
    if not state.get("waiting_for_result", False) or not state.get("last_signal_color"):
        return

    if state["last_result_round_id"] == state["last_round_id"]:
        return

    if not state["history"]:
        return

    last_outcome = state["history"][-1]

    # Só processa se for round novo depois do sinal
    if state["last_signal_round_id"] == state["last_round_id"]:
        return

    state["last_result_round_id"] = state["last_round_id"]
    target = state["last_signal_color"]

    # Apaga sempre o aviso de martingale (se existir)
    await delete_messages(state.get("martingale_message_ids", []))
    state["martingale_message_ids"] = []

    if last_outcome == "🟡":  # Empate
        state["greens_seguidos"] += 1
        state["total_empates"] += 1
        await send_to_channel(green_text(state["greens_seguidos"]))
        await delete_messages([state.get("entrada_message_id")])
        state["entrada_message_id"] = None
        state.update({
            "waiting_for_result": False,
            "last_signal_color": None,
            "martingale_count": 0,
            "last_signal_pattern_id": None,
            "last_signal_sequence": None,
            "last_signal_round_id": None,
            "signal_cooldown": True
        })
        return

    if last_outcome == target:  # Green
        state["greens_seguidos"] += 1
        state["total_greens"] += 1
        await send_to_channel(green_text(state["greens_seguidos"]))
        await delete_messages([state.get("entrada_message_id")])
        state["entrada_message_id"] = None
        state.update({
            "waiting_for_result": False,
            "last_signal_color": None,
            "martingale_count": 0,
            "last_signal_pattern_id": None,
            "last_signal_sequence": None,
            "last_signal_round_id": None,
            "signal_cooldown": True
        })
        return

    # Martingale ou Loss
    if state.get("martingale_count", 0) == 0:
        state["martingale_count"] = 1
        msg_id = await send_to_channel(martingale_text(target))
        if msg_id:
            state["martingale_message_ids"] = [msg_id]
    else:
        state["greens_seguidos"] = 0
        state["total_losses"] += 1
        await send_to_channel("🟥 <b>LOSS 🟥</b>")
        await delete_messages([state.get("entrada_message_id")])
        state["entrada_message_id"] = None
        state.update({
            "waiting_for_result": False,
            "last_signal_color": None,
            "martingale_count": 0,
            "last_signal_pattern_id": None,
            "last_signal_sequence": None,
            "last_signal_round_id": None,
            "signal_cooldown": True
        })

    reset_placar_if_needed()   # verifica se chegou a 10 losses


async def try_send_signal():
    if state["waiting_for_result"]:
        await delete_analise_message()
        return

    if state["signal_cooldown"]:
        await refresh_analise_message()
        return

    if len(state["history"]) < 3:
        await refresh_analise_message()
        return

    pat = find_matching_pattern(state["history"])
    if not pat:
        await refresh_analise_message()
        return

    color = pat["sinal"]
    seq = state["history"][-len(pat["sequencia"]):]

    if (state["last_signal_pattern_id"] == pat["id"] and 
        state["last_signal_sequence"] == seq):
        await refresh_analise_message()
        return

    await delete_analise_message()
    await delete_messages(state["martingale_message_ids"])
    state["martingale_message_ids"] = []

    msg_id = await send_to_channel(main_entry_text(color))
    if msg_id:
        state["entrada_message_id"] = msg_id
        state["waiting_for_result"] = True
        state["last_signal_color"] = color
        state["martingale_count"] = 0
        state["last_signal_pattern_id"] = pat["id"]
        state["last_signal_sequence"] = seq
        state["last_signal_round_id"] = state["last_round_id"]
        logger.info(f"Sinal enviado: {color}")


# ... (api_worker, scheduler_worker, main mantêm-se praticamente iguais)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot parado pelo usuário")
    except Exception as e:
        logger.critical("Erro fatal", exc_info=True)
        asyncio.run(send_error_to_channel(f"ERRO FATAL: {str(e)}"))
