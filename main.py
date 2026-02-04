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

# Configurações
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7345209825:AAE54I0tSUEdomWNOVkdTOFDnvY7jKBC4o0")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "-1003683356410")  # MUDE SE NECESSÁRIO
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
    "greens_sem_gale": 0,
    "greens_gale_1": 0,
    "greens_gale_2": 0,
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
        state["greens_sem_gale"] = 0
        state["greens_gale_1"] = 0
        state["greens_gale_2"] = 0
        state["total_empates"] = 0
        state["total_losses"] = 0
        state["greens_seguidos"] = 0
        logger.info("🔄 Placar resetado (diário ou por 10 losses)")

def calcular_acertividade() -> str:
    total_decisoes = state["total_greens"] + state["total_losses"]
    if total_decisoes == 0:
        return "—"
    perc = (state["total_greens"] / total_decisoes) * 100
    return f"{perc:.1f}%"

def format_placar() -> str:
    acert = calcular_acertividade()
    return (
        "🏆 <b>RESUMO</b> 🏆\n"
        f"✅ Ganhos sem gale: <b>{state['greens_sem_gale']}</b>\n"
        f"🔄 Ganhos gale 1: <b>{state['greens_gale_1']}</b>\n"
        f"🔄 Ganhos gale 2: <b>{state['greens_gale_2']}</b>\n"
        f"🤝 Total empates: <b>{state['total_empates']}</b>\n"
        f"⛔ Losses reais: <b>{state['total_losses']}</b>\n"
        f"─────────────────────────────\n"
        f"🎯 Total greens: <b>{state['total_greens']}</b>\n"
        f"🎯 Acertividade: <b>{acert}</b>"
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
                if k in pl:
                    player_dice = pl[k]
                if k in bk:
                    banker_dice = bk[k]
        if not round_id or not outcome_raw:
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

# =============================================================================
# ESTRATÉGIAS
# =============================================================================

def oposto(cor: str) -> str:
    return "🔵" if cor == "🔴" else "🔴"

def estrategia_repeticao(hist: List[str]):
    if len(hist) >= 5 and all(x == hist[-1] for x in hist[-5:]) and hist[-1] in ("🔵", "🔴"):
        return ("Reversão 5x", oposto(hist[-1]))
    if len(hist) >= 4 and all(x == hist[-1] for x in hist[-4:]) and hist[-1] in ("🔵", "🔴"):
        return ("Reversão 4x", oposto(hist[-1]))
    return None

def estrategia_alternancia(hist: List[str]):
    if len(hist) >= 6:
        last6 = hist[-6:]
        if all(x in ("🔵", "🔴") for x in last6):
            if (last6[0] == last6[2] == last6[4] and 
                last6[1] == last6[3] == last6[5] and 
                last6[0] != last6[1]):
                return ("Alternância 6x", oposto(last6[-1]))
    if len(hist) >= 4:
        last4 = hist[-4:]
        if all(x in ("🔵", "🔴") for x in last4):
            if last4[0] == last4[2] and last4[1] == last4[3] and last4[0] != last4[1]:
                return ("Alternância 4x", oposto(last4[-1]))
    return None

def estrategia_seq_empate(hist: List[str]):
    if len(hist) >= 3:
        if hist[-1] == "🟡" and hist[-2] in ("🔵", "🔴"):
            return ("Pós-Tie Continuação", hist[-2])
        if hist[-2] == "🟡" and hist[-1] in ("🔵", "🔴") and hist[-3] in ("🔵", "🔴"):
            if hist[-1] == hist[-3]:
                return ("Confirmação Pós-Tie", hist[-1])
    return None

def estrategia_tendencia_forte(hist: List[str]):
    window = [x for x in hist[-10:] if x in ("🔵", "🔴")]
    if len(window) >= 7:
        cnt = Counter(window)
        for cor, freq in cnt.most_common(1):
            if freq >= 7:
                return ("Tendência Forte", cor)
    return None

def estrategia_quebra_padrao(hist: List[str]):
    if len(hist) >= 6:
        for i in range(4, min(8, len(hist))):
            seq = hist[-(i+1):-1]
            if all(x == seq[0] for x in seq) and seq[0] in ("🔵", "🔴"):
                if hist[-1] in ("🔵", "🔴") and hist[-1] != seq[0]:
                    return ("Quebra de Sequência", hist[-1])
    return None

def estrategia_recuperacao(hist: List[str]):
    if len(hist) >= 4:
        last4 = [x for x in hist[-4:] if x in ("🔵", "🔴")]
        if len(last4) >= 3:
            if last4[-1] == last4[-2] and last4[-3] != last4[-1]:
                return ("Recuperação", oposto(last4[-1]))
    return None

def estrategia_paridade(player_score, banker_score):
    if player_score is None or banker_score is None:
        return None
    try:
        ps = int(player_score)
        bs = int(banker_score)
        if (ps + bs) % 2 == 0:
            if ps > bs:
                return ("Paridade Favorável", "🔵")
            elif bs > ps:
                return ("Paridade Favorável", "🔴")
    except:
        pass
    return None

# Adicione aqui as outras estratégias que desejar (fibonacci, momentum, gap, etc.)
# Por enquanto deixei as principais para o código rodar bem

def gerar_sinal_estrategia(history: List[str], player_score=None, banker_score=None):
    if len(history) < 5:
        return None, None
    
    tier1 = [estrategia_tendencia_forte, estrategia_quebra_padrao, estrategia_repeticao]          # peso 3
    tier2 = [estrategia_alternancia, estrategia_recuperacao]                                     # peso 2
    tier3 = [estrategia_seq_empate]                                                              # peso 1.5
    tier4 = []  # pode adicionar mais aqui se quiser
    
    votos = {"🔵": 0.0, "🔴": 0.0}
    melhor_estrategia = None
    
    for tier, peso in [(tier1, 3.0), (tier2, 2.0), (tier3, 1.5), (tier4, 1.0)]:
        for func in tier:
            res = func(history)
            if res:
                votos[res[1]] += peso
                if melhor_estrategia is None:
                    melhor_estrategia = res[0]
    
    res_par = estrategia_paridade(player_score, banker_score)
    if res_par:
        votos[res_par[1]] += 0.5
    
    total = votos["🔵"] + votos["🔴"]
    diff = abs(votos["🔵"] - votos["🔴"])
    
    if total >= 4.0 and diff >= 2.0:
        cor = "🔵" if votos["🔵"] > votos["🔴"] else "🔴"
        confianca = (diff / total) * 100 if total > 0 else 0
        nome = f"{melhor_estrategia or 'Multi-estratégia'} ({confianca:.0f}%)"
        return (nome, cor)
    
    return None, None

def main_entry_text(color: str) -> str:
    emoji = color
    return (
        f"🎲 ENTRADA DO CLEVER 🎲\n"
        f"APOSTA NA COR: {emoji}\n"
        f"PROTEJA O TIE 🟡"
    )

def green_text(player_sum: Optional[int], banker_sum: Optional[int]) -> str:
    p = player_sum if player_sum is not None else "?"
    b = banker_sum if banker_sum is not None else "?"
    return (
        f"💰 ENTROU DINHEIRO 💰\n"
        f"🔵 = {p}  &  🔴 = {b}"
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
    acertou = (last_outcome == target)
    is_tie = (last_outcome == "🟡")
    
    player_last = state.get("player_score_last")
    banker_last = state.get("banker_score_last")
    
    if acertou or is_tie:
        state["total_greens"] += 1
        state["greens_seguidos"] += 1
        if state["martingale_count"] == 0:
            state["greens_sem_gale"] += 1
        elif state["martingale_count"] == 1:
            state["greens_gale_1"] += 1
        elif state["martingale_count"] == 2:
            state["greens_gale_2"] += 1
        
        await send_to_channel(green_text(player_last, banker_last))
        await send_to_channel(format_placar())
        
        seq_text = f"SEQUÊNCIA DE {state['greens_seguidos']} GREENS 🔥"
        await send_to_channel(seq_text)
        
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
    if len(state["history"]) < 5:  # aumentado para combinar com gerar_sinal
        await refresh_analise_message()
        return
    
    padrao, cor = gerar_sinal_estrategia(
        state["history"],
        state.get("player_score_last"),
        state.get("banker_score_last")
    )
    
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
    await send_to_channel("🤖 Bot iniciado - procurando sinais...")
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
