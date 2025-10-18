import asyncio
import aiohttp
import logging
from telegram import Bot
from telegram.error import TelegramError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import uuid

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
ultima_mensagem_monitoramento = None
detecao_pausada = False

OUTCOME_MAP = {"PlayerWon": "🔵", "BankerWon": "🔴", "Tie": "🟡"}

# === PADRÕES FIXOS DE TENDÊNCIA ===
PADROES = [
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
    {"id": str(uuid.uuid4()), "sequencia": ["🔴","🔴","🔴","🔵","🔴","🔵"], "sinal": "🔴"},
    {"id": str(uuid.uuid4()), "sequencia": ["🔵","🔵","🔵","🔴","🔵","🔴"], "sinal": "🔵"},
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

async def calcular_probabilidade(padrao, historico):
    """Calcula a probabilidade de acerto do padrão com base no histórico."""
    seq = padrao["sequencia"]
    sinal = padrao["sinal"]
    acertos = 0
    total = 0
    for i in range(len(historico) - len(seq) - 1):
        if historico[i:i+len(seq)] == seq and historico[i+len(seq)] == sinal:
            acertos += 1
        if historico[i:i+len(seq)] == seq:
            total += 1
    return (acertos / total * 100) if total > 0 else 0

async def enviar_sinal(sinal, padrao_id, resultado_id, sequencia):
    """Envia o alerta de sinal no Telegram com probabilidade e apaga mensagem de monitoramento."""
    global sinais_ativos, ultima_mensagem_monitoramento
    if any(s["padrao_id"] == padrao_id for s in sinais_ativos):
        return
    # Apaga a última mensagem de monitoramento, se existir
    if ultima_mensagem_monitoramento:
        try:
            await bot.delete_message(chat_id=CHAT_ID, message_id=ultima_mensagem_monitoramento)
            ultima_mensagem_monitoramento = None
            logging.info("Mensagem de monitoramento apagada ao enviar sinal.")
        except TelegramError as e:
            logging.warning(f"Falha ao deletar mensagem de monitoramento ao enviar sinal: {e}")
    sequencia_str = " ".join(sequencia)
    padrao = next((p for p in PADROES if p["id"] == padrao_id), None)
    prob = await calcular_probabilidade(padrao, historico) if padrao else 0
    msg = f"🎰 CLEVER BOT\n💡 Padrão detectado: {sequencia_str}\n👉 Apostar em: {sinal}\n📊 Probabilidade: {prob:.1f}%"
    try:
        message = await bot.send_message(chat_id=CHAT_ID, text=msg)
        sinais_ativos.append({
            "sinal": sinal,
            "padrao_id": padrao_id,
            "resultado_id": resultado_id,
        })
        logging.info(f"Sinal enviado: {sequencia_str} -> {sinal}")
        return message.message_id
    except TelegramError as e:
        logging.error(f"Erro ao enviar sinal: {e}")

async def enviar_resultado(resultado, player_score, banker_score, resultado_id):
    """Valida o resultado e envia mensagem com contexto do padrão."""
    global sinais_ativos
    try:
        for sinal_ativo in sinais_ativos[:]:
            if sinal_ativo["resultado_id"] == resultado_id:
                continue
            padrao = next((p for p in PADROES if p["id"] == sinal_ativo["padrao_id"]), None)
            seq_str = " ".join(padrao["sequencia"]) if padrao else "Desconhecido"
            if resultado == sinal_ativo["sinal"] or resultado == "🟡":
                if resultado == "🟡":
                    msg = f"🟡 Empate detectado\n🎲 {player_score} x {banker_score}\n📜 Padrão: {seq_str}"
                else:
                    msg = f"✅ SINAL CORRETO\n🏆 Resultado: {resultado}\n🎲 {player_score} x {banker_score}\n📜 Padrão: {seq_str}"
            else:
                msg = f"❌ Sinal incorreto\n🎲 Player {player_score} x Banker {banker_score}\n📜 Padrão: {seq_str}"
            await bot.send_message(chat_id=CHAT_ID, text=msg)
            sinais_ativos.remove(sinal_ativo)
    except TelegramError as e:
        logging.error(f"Erro no envio do resultado: {e}")

async def enviar_monitoramento():
    """Mensagem cíclica de monitoramento com tratamento de erros robusto."""
    global ultima_mensagem_monitoramento
    while True:
        try:
            if not sinais_ativos:
                if ultima_mensagem_monitoramento:
                    try:
                        await bot.delete_message(chat_id=CHAT_ID, message_id=ultima_mensagem_monitoramento)
                        logging.info("Mensagem de monitoramento anterior apagada.")
                    except TelegramError as e:
                        logging.warning(f"Falha ao deletar mensagem de monitoramento: {e}")
                    ultima_mensagem_monitoramento = None
                msg = await bot.send_message(chat_id=CHAT_ID, text="🔎 Monitorando a mesa Bac Bo...")
                ultima_mensagem_monitoramento = msg.message_id
                logging.info("Mensagem de monitoramento enviada com sucesso.")
            await asyncio.sleep(15)
        except TelegramError as e:
            logging.error(f"Erro ao enviar mensagem de monitoramento: {e}")
            ultima_mensagem_monitoramento = None  # Reseta ID em caso de erro
            await asyncio.sleep(15)
        except Exception as e:
            logging.error(f"Erro inesperado no monitoramento: {e}")
            ultima_mensagem_monitoramento = None  # Reseta ID em caso de erro
            await asyncio.sleep(15)

async def main():
    global historico, ultimo_padrao_id, ultimo_resultado_id
    sinais_ativos.clear()  # Garante lista vazia no início
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
        sinais_enviados = 0
        for padrao in PADROES:
            seq_len = len(padrao["sequencia"])
            if len(historico) >= seq_len:
                if historico[-seq_len:] == padrao["sequencia"] and padrao["id"] != ultimo_padrao_id:
                    await enviar_sinal(padrao["sinal"], padrao["id"], resultado_id, padrao["sequencia"])
                    ultimo_padrao_id = padrao["id"]
                    sinais_enviados += 1
                    if sinais_enviados >= 2:  # Limite de 2 sinais por ciclo
                        break
        await asyncio.sleep(2)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Encerrado pelo usuário.")
