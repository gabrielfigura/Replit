import os
import json
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
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8163319902:AAHE9LZ984JCIc-Lezl4WXR2FsGHPEFTxRQ")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "-1003882537733")

API_URL = "https://api.signals-house.com/validate/results?tableId=2&lastResult=13343863"

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

# ─── TIMING CORRIGIDO ───
# Poll rápido (2s) para detectar mudança de rodada o mais cedo possível.
# Sem delay fixo — o sinal é enviado IMEDIATAMENTE após detectar novo resultado.
API_POLL_INTERVAL = 2.0
# Cooldown apenas para evitar duplicação, não para atrasar o sinal.
SIGNAL_COOLDOWN_DURATION = 5

STATE_FILE = "bot_state.json"

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
    "signal_cooldown_until": 0.0,
    "analise_message_id": None,
    "last_reset_date": None,
    "last_analise_refresh": 0.0,
    "last_result_round_id": None,
    "player_score_last": None,
    "banker_score_last": None,
    # Flag removida: "new_result_added" já não controla o timing.
    # Agora usamos detecção direta de mudança de round_id.
}


# ─── PERSISTÊNCIA DO PLACAR (nunca zera) ───

def save_state():
    try:
        data = {
            "total_greens": state["total_greens"],
            "greens_sem_gale": state["greens_sem_gale"],
            "greens_gale_1": state["greens_gale_1"],
            "greens_gale_2": state["greens_gale_2"],
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
        for k in ["total_greens", "greens_sem_gale", "greens_gale_1", "greens_gale_2",
                   "total_empates", "total_losses", "greens_seguidos"]:
            if k in data:
                state[k] = data[k]
        logger.info(f"Estado carregado: Greens={state['total_greens']} Losses={state['total_losses']}")
    except FileNotFoundError:
        logger.info("Nenhum estado anterior encontrado, começando do zero.")
    except Exception as e:
        logger.debug(f"Erro ao carregar estado: {e}")


# ─── TELEGRAM HELPERS ───

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


# ─── TIMING CORRIGIDO: update_history_from_api ───
# Retorna True se uma NOVA rodada foi detectada, False caso contrário.
# Isso permite ao loop principal reagir imediatamente.
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

        # Se o round_id é o mesmo, não há rodada nova
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

        # ─── NOVA RODADA DETECTADA ───
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


# ─── ESTRATÉGIAS (SEM ALTERAÇÃO) ───

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


def main_entry_text(color: str) -> str:
    return (
        f"🎲 ENTRADA CONFIRMADA 🎲\n"
        f"APOSTA NA COR: {color}\n"
        f"PROTEJA O TIE 🟡"
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


# ─── TIMING CORRIGIDO: resolve_after_result ───
# Chamada IMEDIATAMENTE quando nova rodada é detectada.
# Não depende mais de flags — é chamada diretamente pelo loop.
async def resolve_after_result():
    if not state.get("waiting_for_result") or not state.get("last_signal_color"):
        return
    if not state["history"]:
        return
    # Verifica se já processamos este resultado
    if state["last_result_round_id"] == state["last_round_id"]:
        return
    # Garante que o resultado é posterior ao sinal
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
        elif state["martingale_count"] == 2: state["greens_gale_2"] += 1

        green_text = (
            "✅GREEN✅\n"
            "🤖MAIS FOCO E MENOS GANÂNCIA🤖"
        )
        await send_to_channel(green_text)
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
            # CORRIGIDO: cooldown curto para permitir novo sinal rápido
            "signal_cooldown_until": datetime.now().timestamp() + 2
        })
        save_state()
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

        state.update({
            "waiting_for_result": False,
            "last_signal_color": None,
            "martingale_count": 0,
            "entrada_message_id": None,
            "last_signal_pattern": None,
            "last_signal_sequence": None,
            "last_signal_round_id": None,
            # CORRIGIDO: cooldown curto após loss também
            "signal_cooldown_until": datetime.now().timestamp() + 2
        })
        save_state()

    await refresh_analise_message()


# ─── TIMING CORRIGIDO: try_send_signal ───
# Chamada IMEDIATAMENTE após detectar nova rodada e resolver resultado anterior.
# Sem delay fixo — o sinal sai no instante em que a análise é feita.
# O jogador recebe o sinal durante o betting time da próxima rodada.
async def try_send_signal():
    now = datetime.now().timestamp()
    if state["waiting_for_result"]:
        await delete_analise_message()
        return
    if now < state["signal_cooldown_until"]:
        return
    if len(state["history"]) < 3:
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

    # ─── SINAL ENVIADO IMEDIATAMENTE ───
    # Nenhum sleep aqui. O sinal sai assim que a análise termina,
    # que é logo após detectar o fim da rodada anterior.
    msg_id = await send_to_channel(main_entry_text(cor))
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


# ─── TIMING CORRIGIDO: api_worker (LOOP PRINCIPAL) ───
# Fluxo correto:
#   1. Poll rápido (2s) para detectar nova rodada
#   2. Quando nova rodada detectada:
#      a) Resolver resultado anterior (green/gale/loss)
#      b) Enviar novo sinal IMEDIATAMENTE (durante betting time)
#   3. Se não há rodada nova, apenas dorme e tenta de novo
#
# RESULTADO SAI → BOT ANALISA → ENVIA SINAL → NOVA RODADA COMEÇA
async def api_worker():
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                # 1. Verificar se há nova rodada
                nova_rodada = await update_history_from_api(session)

                if nova_rodada:
                    # 2a. Resolver sinal anterior imediatamente
                    await resolve_after_result()
                    # Pequena pausa para o Telegram processar
                    await asyncio.sleep(0.3)
                    # 2b. Tentar enviar novo sinal AGORA (betting time)
                    await try_send_signal()

                # 3. Dormir e verificar de novo
                # Poll a cada 2s para detectar mudanças rápido
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
