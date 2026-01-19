import os
import asyncio
import logging
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
import pytz
from collections import Counter

import numpy as np
from scipy import stats

import aiohttp
from telegram import Bot
from telegram.error import TelegramError
from dotenv import load_dotenv

load_dotenv()

# Configurações
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7345209825:AAE54I0tSUEdomWNOVkdTOFDnvY7jKBC4o0")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "-1003683356410")  # ALTERE SE NECESSÁRIO

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

API_POLL_INTERVAL = 3
SIGNAL_CYCLE_INTERVAL = 5
ANALISE_REFRESH_INTERVAL = 15

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-5s | %(message)s'
)
logger = logging.getLogger("BacBoBot")

bot = Bot(token=TELEGRAM_BOT_TOKEN)

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
    "last_signal_pattern": None,
    "last_signal_sequence": None,
    "last_signal_round_id": None,
    "signal_cooldown": False,
    "analise_message_id": None,
    "last_reset_date": None,
    "last_analise_refresh": 0.0,
    "last_result_round_id": None,
    "player_score_last": None,
    "banker_score_last": None,
}

# ────────────────────────────────────────────────
#     ESTRATÉGIAS AVANÇADAS
# ────────────────────────────────────────────────

def calculate_pattern_correlation(history: List[str], window_size: int = 5) -> Dict[str, float]:
    if len(history) < window_size * 2:
        return {}
    
    color_map = {"🔵": 1, "🔴": -1, "🟡": 0}
    numeric_history = [color_map.get(c, 0) for c in history]
    
    correlations = {}
    for lag in range(1, min(window_size, len(numeric_history)//2)):
        correlation = np.corrcoef(numeric_history[:-lag], numeric_history[lag:])[0, 1]
        if not np.isnan(correlation):
            correlations[f"lag_{lag}"] = correlation
    
    return correlations


def estrategia_correlacao(history: List[str]) -> Optional[Tuple[str, str]]:
    correlations = calculate_pattern_correlation(history)
    if not correlations:
        return None
    
    strongest_lag = max(correlations, key=correlations.get, default=None)
    if strongest_lag is None:
        return None
    
    lag_value = int(strongest_lag.split("_")[1])
    
    if lag_value >= len(history):
        return None
    
    predicted_value = history[-lag_value - 1]
    if predicted_value in ("🔵", "🔴"):
        confidence = abs(correlations[strongest_lag])
        if confidence > 0.5:
            return (f"Correlação (lag {lag_value})", predicted_value)
    
    return None


def estrategia_frequencia_bayesiana(history: List[str]) -> Optional[Tuple[str, str]]:
    if len(history) < 10:
        return None
    
    recent = history[-10:]
    historic = history[:-10] if len(history) > 10 else []
    
    if not historic:
        return None
    
    recent_counts = Counter(recent)
    historic_counts = Counter(historic)
    
    bayes_probs = {}
    for color in ["🔵", "🔴"]:
        if color in recent_counts and color in historic_counts:
            recent_prob = recent_counts[color] / len(recent)
            historic_prob = historic_counts[color] / len(historic)
            bayes_prob = recent_prob * 0.7 + historic_prob * 0.3
            bayes_probs[color] = bayes_prob
    
    if bayes_probs:
        best_color = max(bayes_probs, key=bayes_probs.get)
        confidence = bayes_probs[best_color]
        if confidence > 0.55:
            return ("Frequência Bayesiana", best_color)
    
    return None


def estrategia_markov(history: List[str]) -> Optional[Tuple[str, str]]:
    if len(history) < 6:
        return None
    
    transitions = {}
    
    for i in range(len(history) - 2):
        current_state = (history[i], history[i+1])
        next_state = history[i+2]
        
        if current_state not in transitions:
            transitions[current_state] = {"🔵": 0, "🔴": 0, "🟡": 0}
        
        transitions[current_state][next_state] += 1
    
    if len(history) < 2:
        return None
    
    current_state = (history[-2], history[-1])
    
    if current_state in transitions:
        next_probs = transitions[current_state]
        total = sum(next_probs.values())
        
        if total > 0:
            normalized_probs = {k: v/total for k, v in next_probs.items()}
            
            if normalized_probs.get("🟡", 0) < 0.2:
                normalized_probs.pop("🟡", None)
            
            if normalized_probs:
                best_next = max(normalized_probs, key=normalized_probs.get)
                confidence = normalized_probs[best_next]
                
                if confidence > 0.5:
                    return (f"Markov ({current_state[0]}{current_state[1]})", best_next)
    
    return None


def estrategia_ciclos_ondas(history: List[str]) -> Optional[Tuple[str, str]]:
    if len(history) < 15:
        return None
    
    color_map = {"🔵": 1, "🔴": -1, "🟡": 0}
    numeric_history = [color_map.get(c, 0) for c in history]
    
    try:
        window = min(5, len(numeric_history)//3)
        if window < 2:
            return None
        
        smoothed = []
        for i in range(len(numeric_history) - window + 1):
            smoothed.append(sum(numeric_history[i:i+window]) / window)
        
        peaks = []
        valleys = []
        
        for i in range(1, len(smoothed) - 1):
            if smoothed[i] > smoothed[i-1] and smoothed[i] > smoothed[i+1]:
                peaks.append(i)
            elif smoothed[i] < smoothed[i-1] and smoothed[i] < smoothed[i+1]:
                valleys.append(i)
        
        if len(smoothed) > 0:
            last_idx = len(smoothed) - 1
            near_peak = any(abs(last_idx - p) <= 2 for p in peaks)
            near_valley = any(abs(last_idx - v) <= 2 for v in valleys)
            
            if near_peak and len(history) > 0:
                last_color = history[-1]
                if last_color == "🔵":
                    return ("Ondas (pico)", "🔴")
                elif last_color == "🔴":
                    return ("Ondas (pico)", "🔵")
            
            elif near_valley and len(history) > 0:
                last_color = history[-1]
                if last_color in ("🔵", "🔴"):
                    return ("Ondas (vale)", last_color)
    except Exception:
        pass
    
    return None


def estrategia_desvio_padrao(history: List[str]) -> Optional[Tuple[str, str]]:
    if len(history) < 10:
        return None
    
    color_map = {"🔵": 1, "🔴": -1, "🟡": 0}
    numeric_history = [color_map.get(c, 0) for c in history]
    
    window = min(5, len(numeric_history)//2)
    if window < 2:
        return None
    
    recent_std = np.std(numeric_history[-window:])
    historic_std = np.std(numeric_history[:-window]) if len(numeric_history) > window else 0
    
    if recent_std > 0 and historic_std > 0:
        ratio = recent_std / historic_std
        
        if ratio > 1.5:
            last_color = history[-1]
            if last_color == "🔵":
                return ("Desvio Padrão (alta vol)", "🔴")
            elif last_color == "🔴":
                return ("Desvio Padrão (alta vol)", "🔵")
    
    return None


def gerar_sinal_estrategia(history: List[str], player_score=None, banker_score=None) -> Tuple[Optional[str], Optional[str]]:
    estrategias = [
        estrategia_correlacao,
        estrategia_markov,
        estrategia_frequencia_bayesiana,
        estrategia_ciclos_ondas,
        estrategia_desvio_padrao,
    ]

    for func in estrategias:
        resultado = func(history)
        if resultado is not None:
            nome, cor = resultado
            return nome, cor

    return None, None


# ────────────────────────────────────────────────
#     FUNÇÕES DE INTERFACE E LÓGICA DO BOT
# ────────────────────────────────────────────────

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
    now = datetime.now(ANGOLA_TZ)
    current_date = now.date()
    if state["last_reset_date"] is None or state["last_reset_date"] != current_date:
        state["last_reset_date"] = current_date
        return True
    if state["total_losses"] >= 10:
        return True
    return False


def reset_placar_if_needed():
    if should_reset_placar():
        state["total_greens"] = 0
        state["total_empates"] = 0
        state["total_losses"] = 0
        state["greens_seguidos"] = 0
        logger.info("Placar resetado (diário ou por 10 losses)")


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
        "🎲 <b>ANALISANDO...</b> 🎲\n\n"
        "<i>Aguarde o próximo sinal</i>"
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


async def fetch_api(session: aiohttp.ClientSession) -> Optional[Dict]:
    try:
        async with session.get(API_URL, headers=HEADERS, timeout=12) as resp:
            if resp.status != 200:
                await send_error_to_channel(f"API retornou status {resp.status}")
                return None
            return await resp.json()
    except Exception as e:
        await send_error_to_channel(f"Erro na API: {str(e)}")
        return None


async def update_history_from_api(session):
    reset_placar_if_needed()
    data = await fetch_api(session)
    if not data:
        return
    try:
        if "data" in data:
            data = data["data"]
        round_id = data.get("id")
        outcome_raw = (data.get("result") or {}).get("outcome")
        player_dice = None
        banker_dice = None

        result = data.get("result") or {}
        if isinstance(result, dict):
            pl = result.get("player") or result.get("playerDice") or {}
            bk = result.get("banker") or result.get("bankerDice") or {}
            for k in ("score", "sum", "total", "points"):
                if k in pl: player_dice = pl[k]
                if k in bk: banker_dice = bk[k]

        if not round_id or not outcome_raw:
            return

        outcome = OUTCOME_MAP.get(outcome_raw)
        if not outcome:
            s = str(outcome_raw).lower()
            if "player" in s: outcome = "🔵"
            elif "banker" in s: outcome = "🔴"
            elif any(x in s for x in ["tie", "empate", "draw"]): outcome = "🟡"

        if outcome and state["last_round_id"] != round_id:
            state["last_round_id"] = round_id
            state["history"].append(outcome)
            if player_dice is not None and banker_dice is not None:
                state["player_score_last"] = player_dice
                state["banker_score_last"] = banker_dice
            if len(state["history"]) > 200:
                state["history"].pop(0)
            logger.info(f"Novo resultado → {outcome} | round {round_id}")
            state["signal_cooldown"] = False
    except Exception as e:
        await send_error_to_channel(f"Erro processando API: {str(e)}")


def main_entry_text(color: str) -> str:
    cor_nome = "AZUL" if color == "🔵" else "VERMELHO"
    emoji = color
    return (
        f"🎲 <b>CLEVER_M</b> 🎲\n"
        f"🧠 APOSTA EM: <b>{emoji} {cor_nome}</b>\n"
        f"🛡️ Proteja o TIE <b>🟡</b>\n"
        f"<b>FAZER ATÉ 2 GALE</b>\n"
        f"🤑 <b>VAI ENTRAR DINHEIRO</b> 🤑"
    )


def green_text() -> str:
    return (
        "🤡 <b>ENTROU DINHEIRO</b> 🤡\n"
        "🎲 <b>MAIS FOCO E MENOS GANÂNCIA</b> 🎲"
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
    if not state.get("waiting_for_result", False) or not state.get("last_signal_color"):
        return

    if state["last_result_round_id"] == state["last_round_id"]:
        return

    if not state["history"]:
        return

    last_outcome = state["history"][-1]

    if state["last_signal_round_id"] == state["last_round_id"]:
        return

    state["last_result_round_id"] = state["last_round_id"]
    target = state["last_signal_color"]

    placar_text = format_placar()

    if last_outcome in ("🟡", target):
        if last_outcome == "🟡":
            state["total_empates"] += 1
            state["greens_seguidos"] = 0
        else:
            state["greens_seguidos"] += 1
            state["total_greens"] += 1

        await send_to_channel(green_text())
        await send_to_channel(placar_text)

        await clear_gale_messages()

        state.update({
            "waiting_for_result": False,
            "last_signal_color": None,
            "martingale_count": 0,
            "entrada_message_id": None,
            "last_signal_pattern": None,
            "last_signal_sequence": None,
            "last_signal_round_id": None,
            "signal_cooldown": True
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
        await send_to_channel("🟥 <b>LOSS 🟥</b>")
        await send_to_channel(placar_text)

        await clear_gale_messages()

        state.update({
            "waiting_for_result": False,
            "last_signal_color": None,
            "martingale_count": 0,
            "entrada_message_id": None,
            "last_signal_pattern": None,
            "last_signal_sequence": None,
            "last_signal_round_id": None,
            "signal_cooldown": True
        })

    reset_placar_if_needed()
    await refresh_analise_message()


async def try_send_signal():
    if state["waiting_for_result"]:
        await delete_analise_message()
        return

    if state["signal_cooldown"]:
        await refresh_analise_message()
        return

    if len(state["history"]) < 10:
        await refresh_analise_message()
        return

    padrao, cor = gerar_sinal_estrategia(state["history"])

    if not cor:
        await refresh_analise_message()
        return

    seq_str = "".join(state["history"][-8:])
    if state["last_signal_pattern"] == padrao and state["last_signal_sequence"] == seq_str:
        await refresh_analise_message()
        return

    await delete_analise_message()
    state["martingale_message_ids"] = []

    msg_id = await send_to_channel(main_entry_text(cor))
    if msg_id:
        state["entrada_message_id"] = msg_id
        state["waiting_for_result"] = True
        state["last_signal_color"] = cor
        state["martingale_count"] = 0
        state["last_signal_pattern"] = padrao
        state["last_signal_sequence"] = seq_str
        state["last_signal_round_id"] = state["last_round_id"]
        logger.info(f"Sinal enviado: {cor} | Estratégia: {padrao}")


async def api_worker():
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                await update_history_from_api(session)
                await resolve_after_result()
            except Exception as e:
                logger.exception("Erro no api_worker")
                await send_error_to_channel(f"Erro grave no loop da API:\n<code>{str(e)}</code>")
                await asyncio.sleep(10)
            await asyncio.sleep(API_POLL_INTERVAL)


async def scheduler_worker():
    await asyncio.sleep(3)
    while True:
        try:
            await refresh_analise_message()
            await try_send_signal()
        except Exception as e:
            logger.exception("Erro no scheduler")
            await send_error_to_channel(f"Erro no envio de sinais:\n<code>{str(e)}</code>")
        await asyncio.sleep(SIGNAL_CYCLE_INTERVAL)


async def main():
    logger.info("🤖 Bot iniciado...")
    await send_to_channel("🤖 Bot iniciado - usando estratégias avançadas...")
    await asyncio.gather(api_worker(), scheduler_worker())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot parado pelo usuário")
    except Exception as e:
        logger.critical("Erro fatal", exc_info=True)
        try:
            asyncio.run(send_error_to_channel(f"ERRO FATAL: {str(e)}"))
        except:
            pass
