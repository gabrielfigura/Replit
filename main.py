import asyncio
import aiohttp
import logging
from telegram import Bot
from telegram.error import TelegramError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from collections import Counter
import uuid  # ✅ necessário para gerar IDs dos padrões


# Configurações fixas
BOT_TOKEN = "7758723414:AAF-Zq1QPoGy2IS-iK2Wh28PfexP0_mmHHc"
CHAT_ID = "-1002506692600"
API_URL = "https://api.casinoscores.com/svc-evolution-game-events/api/bacbo/latest"

bot = Bot(token=BOT_TOKEN)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

historico = []
ultimo_padrao_id = None
ultimo_resultado_id = None
sinais_ativos = []
placar = {"ganhos_seguidos": 0, "losses": 0, "empates": 0}
ultima_mensagem_monitoramento = None
detecao_pausada = False


OUTCOME_MAP = {"PlayerWon": "🔵", "BankerWon": "🔴", "Tie": "🟡"}


# === PADRÕES FIXOS DE TENDÊNCIA (sem gale) ===
PADROES = [
    {"id": str(uuid.uuid4()), "sequencia": ["🔴","🔴","🔵"], "sinal": "🔵"},
    {"id": str(uuid.uuid4()), "sequencia": ["🔵","🔵","🔴"], "sinal": "🔴"},
    {"id": str(uuid.uuid4()), "sequencia": ["🔴","🔴","🔴"], "sinal": "🔵"},
    {"id": str(uuid.uuid4()), "sequencia": ["🔵","🔵","🔵"], "sinal": "🔴"},
    {"id": str(uuid.uuid4()), "sequencia": ["🔴","🔵","🔴"], "sinal": "🔵"},
    {"id": str(uuid.uuid4()), "sequencia": ["🔵","🔴","🔵"], "sinal": "🔴"},
    {"id": str(uuid.uuid4()), "sequencia": ["🔴","🔵","🔵","🔴"], "sinal": "🔵"},
    {"id": str(uuid.uuid4()), "sequencia": ["🔵","🔴","🔴","🔵"], "sinal": "🔴"},
    {"id": str(uuid.uuid4()), "sequencia": ["🔴","🔴","🔵","🔴","🔴"], "sinal": "🔵"},
    {"id": str(uuid.uuid4()), "sequencia": ["🔵","🔵","🔴","🔵","🔵"], "sinal": "🔴"},
    {"id": str(uuid.uuid4()), "sequencia": ["🔴","🔵","🔵","🔵"], "sinal": "🔴"},
    {"id": str(uuid.uuid4()), "sequencia": ["🔵","🔴","🔴","🔴"], "sinal": "🔵"},
    {"id": str(uuid.uuid4()), "sequencia": ["🔵","🔴","🔵","🔵"], "sinal": "🔴"},
    {"id": str(uuid.uuid4()), "sequencia": ["🔴","🔵","🔴","🔴"], "sinal": "🔵"},
    {"id": str(uuid.uuid4()), "sequencia": ["🔴","🔴","🔵","🔵"], "sinal": "🔴"},
    {"id": str(uuid.uuid4()), "sequencia": ["🔵","🔵","🔴","🔴"], "sinal": "🔵"},
    {"id": str(uuid.uuid4()), "sequencia": ["🔵","🔴","🔵","🔴","🔵"], "sinal": "🔵"},
    {"id": str(uuid.uuid4()), "sequencia": ["🔴","🔵","🔴","🔵","🔴"], "sinal": "🔴"},
    {"id": str(uuid.uuid4()), "sequencia": ["🔴","🔵","🔵","🔴","🔵"], "sinal": "🔵"},
    {"id": str(uuid.uuid4()), "sequencia": ["🔵","🔴","🔴","🔵","🔴"], "sinal": "🔴"},
]


@retry(stop=stop_after_attempt(7), wait=wait_exponential(multiplier=1, min=4, max=60))
async def fetch_resultado():
    """Lê o resultado da API em tempo real."""
    async with aiohttp.ClientSession() as session:
        async with session.get(API_URL, timeout=aiohttp.ClientTimeout(total=30)) as response:
            if response.status != 200:
                return None, None, None, None
            data = await response.json()
            if 'data' not in data or 'result' not in data['data']:
                return None, None, None, None
            if data['data'].get('status') != 'Resolved':
                return None, None, None, None
            resultado_id = data['id']
            outcome = data['data']['result']['outcome']
            if outcome not in OUTCOME_MAP:
                return None, None, None, None
            resultado = OUTCOME_MAP[outcome]
            player_score = data['data']['result'].get('playerDice', {}).get('score', 0)
            banker_score = data['data']['result'].get('bankerDice', {}).get('score', 0)
            return resultado, resultado_id, player_score, banker_score


async def enviar_sinal(sinal, padrao_id, resultado_id, sequencia):
    """Envia o alerta de sinal no Telegram."""
    global sinais_ativos
    if any(s["padrao_id"] == padrao_id for s in sinais_ativos):
        return
    sequencia_str = " ".join(sequencia)
    msg = f"🎰 CLEVER BOT\n💡 Padrão detectado: {sequencia_str}\n👉 Apostar em: {sinal}"
    message = await bot.send_message(chat_id=CHAT_ID, text=msg)
    sinais_ativos.append({
        "sinal": sinal,
        "padrao_id": padrao_id,
        "resultado_id": resultado_id,
    })
    return message.message_id


async def enviar_placar():
    """Exibe o placar atual."""
    total_acertos = placar["ganhos_seguidos"] + placar["empates"]
    total_sinais = total_acertos + placar["losses"]
    precisao = (total_acertos / total_sinais * 100) if total_sinais > 0 else 0.0
    msg = (
        f"📊 STATUS:\n"
        f"✅ Acertos: {placar['ganhos_seguidos']}\n"
        f"🟡 Empates: {placar['empates']}\n"
        f"❌ Erros: {placar['losses']}\n"
        f"🎯 Precisão: {precisao:.2f}%"
    )
    await bot.send_message(chat_id=CHAT_ID, text=msg)


# === VALIDAÇÃO DE RESULTADOS (sem gale, tempo real) ===
async def enviar_resultado(resultado, player_score, banker_score, resultado_id):
    """Valida o resultado e registra no placar sem gale."""
    global placar, sinais_ativos

    try:
        for sinal_ativo in sinais_ativos[:]:
            if sinal_ativo["resultado_id"] == resultado_id:
                continue

            if resultado == sinal_ativo["sinal"] or resultado == "🟡":
                if resultado == "🟡":
                    placar["empates"] += 1
                    msg = f"🟡 Empate detectado\n🎲 {player_score} x {banker_score}"
                else:
                    placar["ganhos_seguidos"] += 1
                    msg = f"✅ SINAL CORRETO\n🏆 Resultado: {resultado}\n🎲 {player_score} x {banker_score}"
            else:
                placar["losses"] += 1
                msg = f"❌ Sinal incorreto\n🎲 Player {player_score} x Banker {banker_score}"

            await bot.send_message(chat_id=CHAT_ID, text=msg)
            await enviar_placar()
            sinais_ativos.remove(sinal_ativo)
    except TelegramError as e:
        logging.error(f"Erro no envio do resultado: {e}")


async def enviar_monitoramento():
    """Mensagem cíclica de monitoramento."""
    global ultima_mensagem_monitoramento
    while True:
        try:
            if not sinais_ativos:
                if ultima_mensagem_monitoramento:
                    await bot.delete_message(chat_id=CHAT_ID, message_id=ultima_mensagem_monitoramento)
                msg = await bot.send_message(chat_id=CHAT_ID, text="🔎 Monitorando a mesa Bac Bo...")
                ultima_mensagem_monitoramento = msg.message_id
            await asyncio.sleep(15)
        except TelegramError:
            await asyncio.sleep(15)


async def main():
    global historico, ultimo_padrao_id, ultimo_resultado_id

    asyncio.create_task(enviar_monitoramento())
    await bot.send_message(chat_id=CHAT_ID, text="🚀 CLEVER BOT iniciado (modo sem gale).")

    while True:
        resultado, resultado_id, player_score, banker_score = await fetch_resultado()
        if not resultado or not resultado_id:
            await asyncio.sleep(2)
            continue
        if resultado_id == ultimo_resultado_id:
            await asyncio.sleep(2)
            continue

        ultimo_resultado_id = resultado_id
        historico.append(resultado)
        if len(historico) > 50:
            historico.pop(0)

        await enviar_resultado(resultado, player_score, banker_score, resultado_id)

        for padrao in PADROES:
            seq_len = len(padrao["sequencia"])
            if len(historico) >= seq_len:
                if historico[-seq_len:] == padrao["sequencia"] and padrao["id"] != ultimo_padrao_id:
                    await enviar_sinal(padrao["sinal"], padrao["id"], resultado_id, padrao["sequencia"])
                    ultimo_padrao_id = padrao["id"]

        await asyncio.sleep(2)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Encerrado pelo usuário.")
