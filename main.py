import os
import json
import asyncio
import logging
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
import pytz
from collections import Counter, defaultdict
import aiohttp
from telegram import Bot
from telegram.error import TelegramError
from dotenv import load_dotenv

load_dotenv()

# Configurações
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8163319902:AAHE9LZ984JCIc-Lezl4WXR2FsGHPEFTxRQ")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "-1003882537733")
API_URL = "https://api.signals-house.com/validate/results?tableId=1&lastResult=13412758"
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
    "Player": "🔵",
    "Banker": "🔴",
    "🔵": "🔵",
    "🔴": "🔴",
    "🟡": "🟡",
}

# ─── TIMING ───
API_POLL_INTERVAL = 2.0
SIGNAL_COOLDOWN_DURATION = 5
STATE_FILE = "bot_state.json"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-5s | %(message)s'
)
logger = logging.getLogger("BacBoBot")

bot = Bot(token=TELEGRAM_BOT_TOKEN)

# ─── STICKERS ───
GREEN_STICKER_ID = "CAACAgEAAxkBAAMEabgkKtcniqUmvsslUXGIxeotNJUAAucFAAKI8vFGUAABY6O9nCdgOgQ"
LOSS_STICKER_ID = "CAACAgEAAxkBAAMFabgkoGh5GBLnZhz6GZo0quOYvJkAAlIGAAJ8lPBGs1rHcUE1tXQ6BA"

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
    "greens_sem_gale": 0,
    "greens_gale_1": 0,
    "total_empates": 0,
    "total_losses": 0,
    "last_signal_pattern": None,
    "last_signal_sequence": None,
    "last_signal_round_id": None,
    "signal_cooldown_until": 0.0,
    "analise_message_id": None,
    "last_reset_date": None,
    "last_analise_refresh": 0.0,
    "last_result_round_id": None,
    "player_score_last": None,
    "banker_score_last": None,
}

# ─── PADRÕES CONFIRMADOS ───
PATTERNS = [
    {"id": 10, "sequencia": ["🔵", "🔴"], "sinal": "🔵"},
    {"id": 11, "sequencia": ["🔴", "🔵"], "sinal": "🔴"},
    {"id": 13, "sequencia": ["🔵", "🔵", "🔵", "🔴", "🔴", "🔵", "🔵"], "sinal": "🔴"},
    {"id": 14, "sequencia": ["🔴", "🔴", "🔴", "🔵", "🔵", "🔴", "🔴"], "sinal": "🔵"},
    {"id": 15, "sequencia": ["🔴", "🔴", "🟡"], "sinal": "🔴"},
    {"id": 16, "sequencia": ["🔵", "🔵", "🟡"], "sinal": "🔵"},
    {"id": 17, "sequencia": ["🔴", "🔴", "🔵", "🔵", "🔴"], "sinal": "🔴"},
    {"id": 18, "sequencia": ["🔵", "🔵", "🔴", "🔴", "🔵"], "sinal": "🔵"},
    {"id": 19, "sequencia": ["🔴", "🔵", "🔴", "🔴"], "sinal": "🔵"},
    {"id": 20, "sequencia": ["🔵", "🔴", "🔵", "🔵"], "sinal": "🔴"},
    {"id": 21, "sequencia": ["🔵", "🔵", "🔵", "🔴", "🔵", "🔵"], "sinal": "🔵"},
    {"id": 22, "sequencia": ["🔴", "🔴", "🔴", "🔵", "🔴", "🔴"], "sinal": "🔴"},
    {"id": 23, "sequencia": ["🔵", "🔵", "🔴", "🔵", "🔵"], "sinal": "🔴"},
    {"id": 24, "sequencia": ["🔴", "🔴", "🔵", "🔴", "🔴"], "sinal": "🔵"},
    {"id": 25, "sequencia": ["🔵", "🔵", "🔵", "🔵"], "sinal": "🔵"},
    {"id": 26, "sequencia": ["🔴", "🔴", "🔴", "🔴"], "sinal": "🔴"},
    {"id": 34, "sequencia": ["🔵", "🔵", "🔵"], "sinal": "🔴"},
    {"id": 35, "sequencia": ["🔴", "🔴", "🟡"], "sinal": "🔴"},
    {"id": 36, "sequencia": ["🔵", "🔵", "🟡"], "sinal": "🔵"},
    {"id": 39, "sequencia": ["🔴", "🟡", "🔴", "🔵"], "sinal": "🔵"},
    {"id": 40, "sequencia": ["🔵", "🟡", "🔵", "🔴"], "sinal": "🔴"},
    {"id": 41, "sequencia": ["🔴", "🔵", "🟡", "🔴"], "sinal": "🔴"},
    {"id": 42, "sequencia": ["🔵", "🔴", "🟡", "🔵"], "sinal": "🔵"},
    {"id": 43, "sequencia": ["🔴", "🔴", "🔵", "🟡"], "sinal": "🔴"},
    {"id": 44, "sequencia": ["🔵", "🔵", "🔴", "🟡"], "sinal": "🔵"},
    {"id": 45, "sequencia": ["🔵", "🟡", "🟡"], "sinal": "🔵"},
    {"id": 46, "sequencia": ["🔴", "🟡", "🟡"], "sinal": "🔴"},
    {"id": 1, "sequencia": ["🔵", "🔴", "🔵", "🔴"], "sinal": "🔵"},
    {"id": 2, "sequencia": ["🔴", "🔴", "🔴", "🔴", "🔴"], "sinal": "🔴"},
    {"id": 3, "sequencia": ["🔵", "🔵", "🔵", "🔵", "🔵"], "sinal": "🔵"},
    {"id": 4, "sequencia": ["🔴", "🔴", "🔵", "🔵"], "sinal": "🔴"},
    {"id": 5, "sequencia": ["🔴", "🔵", "🔴", "🔵"], "sinal": "🔴"},
    {"id": 6, "sequencia": ["🔴", "🔴", "🔴", "🔴", "🔵"], "sinal": "🔵"},
    {"id": 7, "sequencia": ["🔵", "🔵", "🔵", "🔵", "🔴"], "sinal": "🔴"},
    {"id": 8, "sequencia": ["🔴", "🔵", "🔴", "🔵", "🔴"], "sinal": "🔵"},
    {"id": 9, "sequencia": ["🔵", "🔴", "🔵", "🔴", "🔵"], "sinal": "🔴"},
    {"id": 249, "sequencia": ["🔴", "🔵", "🔵", "🔴"], "sinal": "🔴"},
    {"id": 150, "sequencia": ["🔵", "🔴", "🔴", "🔵"], "sinal": "🔵"},
    {"id": 420, "sequencia": ["🔴", "🟡", "🔴"], "sinal": "🔴"},
    {"id": 424, "sequencia": ["🔵", "🟡", "🔵"], "sinal": "🔵"},
    {"id": 525, "sequencia": ["🔴", "🔴", "🔴", "🔵"], "sinal": "🔵"},
    {"id": 526, "sequencia": ["🔵", "🔵", "🔵", "🔴"], "sinal": "🔴"},
    {"id": 103, "sequencia": ["🔴", "🔵", "🔴", "🔵"], "sinal": "🔴"},
    {"id": 202, "sequencia": ["🔵", "🔴", "🔵", "🔴"], "sinal": "🔵"},
    {"id": 31, "sequencia": ["🔴", "🟡", "🔴", "🟡"], "sinal": "🔴"},
    {"id": 40, "sequencia": ["🟡", "🔴", "🟡", "🔴"], "sinal": "🔵"},
    {"id": 51, "sequencia": ["🔵", "🟡", "🔵", "🟡"], "sinal": "🔵"},
    {"id": 63, "sequencia": ["🟡", "🔵", "🟡", "🔵"], "sinal": "🔵"},
    {"id": 72, "sequencia": ["🔴", "🔴", "🔴", "🔴", "🔴", "🔴"], "sinal": "🔴"},
    {"id": 87, "sequencia": ["🔵", "🔵", "🔵", "🔵", "🔵", "🔵"], "sinal": "🔵"},
    {"id": 95, "sequencia": ["🟡", "🟡", "🟡", "🟡"], "sinal": "🟡"},
    {"id": 120, "sequencia": ["🔴", "🔴", "🔴", "🔵"], "sinal": "🔵"},
    {"id": 110, "sequencia": ["🔵", "🔵", "🔵", "🔴"], "sinal": "🔴"},
    {"id": 124, "sequencia": ["🔴", "🔴", "🔵"], "sinal": "🔵"},
    {"id": 131, "sequencia": ["🔵", "🔵", "🔴"], "sinal": "🔴"},
    {"id": 142, "sequencia": ["🔵", "🔴", "🔵"], "sinal": "🔵"},
    {"id": 157, "sequencia": ["🔴", "🔵", "🔴"], "sinal": "🔴"},
    {"id": 160, "sequencia": ["🔵", "🔴", "🔵", "🔴", "🔴"], "sinal": "🔴"},
    {"id": 144, "sequencia": ["🔵", "🔴", "🔵", "🔴", "🔴"], "sinal": "🔴"},
]

# Ordenar por sequência mais longa primeiro (prioridade ao padrão mais específico)
PATTERNS.sort(key=lambda p: len(p["sequencia"]), reverse=True)


# ─── PERSISTÊNCIA DO PLACAR ───
def save_state():
    try:
        data = {
            "total_greens": state["total_greens"],
            "greens_sem_gale": state["greens_sem_gale"],
            "greens_gale_1": state["greens_gale_1"],
            "total_empates": state["total_empates"],
            "total_losses": state["total_losses"],
            "greens_seguidos": state["greens_seguidos"],
        }
        with open(STATE_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.debug(f"Erro ao salvar estado: {e}")


def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
        for k in ["total_greens", "greens_sem_gale", "greens_gale_1",
                  "total_empates", "total_losses", "greens_seguidos"]:
            if k in data:
                state[k] = data[k]
        logger.info(f"Estado carregado: Greens={state['total_greens']} Losses={state['total_losses']}")
    except FileNotFoundError:
        logger.info("Nenhum estado anterior encontrado, começando do zero.")
    except Exception as e:
        logger.debug(f"Erro ao carregar estado: {e}")


# ─── TELEGRAM HELPERS ───
async def send_to_channel(text: str, parse_mode="HTML", disable_preview=True) -> Optional[int]:
    try:
        msg = await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=text,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_preview
        )
        return msg.message_id
    except Exception as e:
        logger.error(f"Erro ao enviar texto: {e}")
        return None


async def send_sticker_to_channel(sticker_id: str) -> Optional[int]:
    try:
        msg = await bot.send_sticker(
            chat_id=TELEGRAM_CHANNEL_ID,
            sticker=sticker_id
        )
        return msg.message_id
    except Exception as e:
        logger.error(f"Erro ao enviar sticker: {e}")
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
        f"📊 Placar atual 🟢 {state['total_greens']} 🔴 {state['total_losses']}\n"
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


# ─── API ───
async def fetch_api(session: aiohttp.ClientSession) -> Optional[Dict]:
    try:
        async with session.get(API_URL, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=7)) as resp:
            if resp.status == 200:
                return await resp.json()
            return None
    except:
        return None


async def update_history_from_api(session) -> bool:
    data = await fetch_api(session)
    if not data:
        return False
    try:
        items = data.get("data", [])
        if not isinstance(items, list) or len(items) == 0:
            return False
        latest = items[0]
        round_id = latest.get("id")
        if not round_id:
            return False
        if state["last_round_id"] == round_id:
            return False
        outcome_raw = latest.get("result")
        if not outcome_raw:
            return False
        score = latest.get("score")
        outcome = OUTCOME_MAP.get(outcome_raw)
        if not outcome:
            s = str(outcome_raw or "").lower()
            if "player" in s: outcome = "🔵"
            elif "banker" in s: outcome = "🔴"
            elif any(x in s for x in ["tie", "empate", "draw"]): outcome = "🟡"
        if not outcome:
            return False
        state["last_round_id"] = round_id
        state["history"].append(outcome)
        state["player_score_last"] = None
        state["banker_score_last"] = None
        if len(state["history"]) > 200:
            state["history"].pop(0)
        logger.info(f"🔔 NOVA RODADA DETECTADA: {outcome} (round {round_id}, score={score})")
        return True
    except Exception as e:
        logger.debug(f"Erro processando API: {e}")
        return False


# ─── MOTOR DE DECISÃO (PATTERN MATCHING) ───
def gerar_sinal_estrategia(history: List[str], player_score=None, banker_score=None) -> Tuple[Optional[str], Optional[str]]:
    if len(history) < 2:
        return None, None

    for pattern in PATTERNS:
        seq = pattern["sequencia"]
        seq_len = len(seq)
        if len(history) >= seq_len:
            if history[-seq_len:] == seq:
                nome = f"PATTERN-ID: {pattern['id']}"
                return nome, pattern["sinal"]

    return None, None


# ─── MENSAGEM DE SINAL ───
def main_entry_text(color: str) -> str:
    return (
        f"🧠 | Sinal confirmado\n"
        f"🎲 | Mesa Bacbo live\n"
        f"⚔️ | Aposte no {color} + 🟠\n"
        f"♻️ | Fazer máximo G1\n"
        f"💻 | Abra o jogo pelo link abaixo ⤵️\n"
        f"\n"
        f'<a href="https://btt-pt.hopghpfa.com/pt/casino?partner=p8506p33116p4649#registration-bonus">👉 Regista-te aqui: BETILT</a>'
    )


async def send_gale_warning(level: int):
    if level != 1:
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
    if not state["history"]:
        return
    if state["last_result_round_id"] == state["last_round_id"]:
        return
    if state["last_signal_round_id"] and state["last_signal_round_id"] >= state["last_round_id"]:
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
        await send_sticker_to_channel(GREEN_STICKER_ID)
        await send_to_channel(format_placar())
        await clear_gale_messages()
        state.update({
            "waiting_for_result": False,
            "last_signal_color": None,
            "martingale_count": 0,
            "entrada_message_id": None,
            "last_signal_pattern": None,
            "last_signal_sequence": None,
            "last_signal_round_id": None,
            "signal_cooldown_until": datetime.now().timestamp() + 2
        })
        save_state()
        return

    state["martingale_count"] += 1
    if state["martingale_count"] == 1:
        await send_gale_warning(1)

    if state["martingale_count"] >= 2:
        state["greens_seguidos"] = 0
        state["total_losses"] += 1
        await send_sticker_to_channel(LOSS_STICKER_ID)
        await send_to_channel(format_placar())
        await clear_gale_messages()
        state.update({
            "waiting_for_result": False,
            "last_signal_color": None,
            "martingale_count": 0,
            "entrada_message_id": None,
            "last_signal_pattern": None,
            "last_signal_sequence": None,
            "last_signal_round_id": None,
            "signal_cooldown_until": datetime.now().timestamp() + 2
        })
        save_state()

    await refresh_analise_message()


async def try_send_signal():
    now = datetime.now().timestamp()
    if state["waiting_for_result"]:
        await delete_analise_message()
        return
    if now < state["signal_cooldown_until"]:
        return
    if len(state["history"]) < 2:
        return

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

    msg_id = await send_to_channel(main_entry_text(cor), disable_preview=False)
    if msg_id:
        state["entrada_message_id"] = msg_id
        state["waiting_for_result"] = True
        state["last_signal_color"] = cor
        state["martingale_count"] = 0
        state["last_signal_pattern"] = padrao
        state["last_signal_sequence"] = seq
        state["last_signal_round_id"] = state["last_round_id"]
        state["signal_cooldown_until"] = now + SIGNAL_COOLDOWN_DURATION
        logger.info(f"⚡ SINAL ENVIADO → {cor} ({padrao}) — durante betting time")


async def api_worker():
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                nova_rodada = await update_history_from_api(session)
                if nova_rodada:
                    await resolve_after_result()
                    await asyncio.sleep(0.3)
                    await try_send_signal()
                await asyncio.sleep(API_POLL_INTERVAL)
            except Exception as e:
                logger.debug(f"Erro loop principal: {e}")
                await asyncio.sleep(API_POLL_INTERVAL)


async def main():
    load_state()
    logger.info("Bot iniciado...")
    await send_to_channel("🤖 BOT INICIADO 🤖")
    await refresh_analise_message()
    await api_worker()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot parado pelo usuário")
    except Exception as e:
        logger.critical("Erro fatal", exc_info=True)
