import asyncio
import aiohttp
import logging
from telegram import Bot
from telegram.error import TelegramError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from collections import Counter
import uuid

# Configurações do Bot (valores fixos para teste)
BOT_TOKEN = "7758723414:AAF-Zq1QPoGy2IS-iK2Wh28PfexP0_mmHHc"
CHAT_ID = "-1002506692600"
API_URL = "https://api.casinoscores.com/svc-evolution-game-events/api/bacbo/latest"

# Inicializar o bot
bot = Bot(token=BOT_TOKEN)

# Configuração de logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")

# Histórico e estado
historico = []
ultimo_padrao_id = None
ultimo_resultado_id = None
sinais_ativos = []
placar = {
    "ganhos_seguidos": 0,
    "ganhos_gale1": 0,
    "ganhos_gale2": 0,
    "losses": 0,
    "empates": 0   # 👈 Novo campo para empates
}
rodadas_desde_erro = 0
ultima_mensagem_monitoramento = None
detecao_pausada = False

# Mapeamento de outcomes para emojis
OUTCOME_MAP = {
    "PlayerWon": "🔵",
    "BankerWon": "🔴",
    "Tie": "🟡"
}

# Padrões
PADROES = [
    {"id": 26, "sequencia": ["🔴", "🔵", "🔴", "🔵", "🔴"], "sinal": "🔴"},
    {"id": 209, "sequencia": ["🔵", "🔴", "🔵", "🔴", "🔵"], "sinal": "🔵"},
    {"id": 308, "sequencia": ["🔵", "🔴", "🔴", "🔴", "🔵", "🔵", "🔴"], "sinal": "🔵"},
    {"id": 103, "sequencia": ["🔴", "🔵", "🔵", "🔵", "🔴", "🔴", "🔵"], "sinal": "🔴"},
    {"id": 107, "sequencia": ["🔵", "🔴", "🔴", "🔴", "🔵", "🔵", "🔴"], "sinal": "🔵"},
    {"id": 506, "sequencia": ["🔴", "🔵", "🔴", "🔴", "🔴", "🔴", "🔴", "🔵", "🔵", "🔵", "🔴", "🔴"], "sinal": "🔵"},
    {"id": 54, "sequencia": ["🔵", "🔴", "🔵", "🔵", "🔵", "🔵", "🔵", "🔴", "🔴", "🔴", "🔵", "🔵"], "sinal": "🔴"},
    {"id": 780, "sequencia": ["🔴", "🔵", "🔴", "🔵", "🔵", "🔴", "🔴", "🔴"], "sinal": "🔵"},
    {"id": 378, "sequencia": ["🔵", "🔴", "🔵", "🔴", "🔴", "🔵", "🔵", "🔵"], "sinal": "🔴"},
    {"id": 270, "sequencia": ["🔴", "🔵", "🔴", "🔴", "🔴", "🔴"], "sinal": "🔵"},
    {"id": 341, "sequencia": ["🔵", "🔴", "🔵", "🔵", "🔵", "🔵"], "sinal": "🔴"},
    {"id": 708, "sequencia": ["🔴", "🔵", "🔴", "🔵", "🔵", "🔴", "🔴", "🔵"], "sinal": "🔵"},
    {"id": 43, "sequencia": ["🔵", "🔴", "🔵", "🔴", "🔴", "🔵", "🔵", "🔴"], "sinal": "🔴"},
    {"id": 444, "sequencia": ["🔴", "🔵", "🔴", "🔵", "🔵", "🔴", "🔴", "🔵", "🔵"], "sinal": "🔴"},
    {"id": 123, "sequencia": ["🔵", "🔴", "🔵", "🔴", "🔴", "🔵", "🔵", "🔴", "🔴"], "sinal": "🔵"},
    {"id": 237, "sequencia": ["🔵", "🔴", "🔵", "🔴", "🔴", "🔵", "🔴", "🔴", "🔵"], "sinal": "🔴"},
    {"id": 870, "sequencia": ["🔴", "🔵", "🔴", "🔵", "🔵", "🔴", "🔵", "🔵", "🔴"], "sinal": "🔵"},
    {"id": 654, "sequencia": ["🔵", "🔴", "🔵", "🔵", "🔵", "🔵", "🔴", "🔴", "🔴", "🔴"], "sinal": "🔵"},
    {"id": 555, "sequencia": ["🔴", "🔵", "🔴", "🔴", "🔴", "🔴", "🔵", "🔵", "🔵", "🔵"], "sinal": "🔴"},
    {"id": 64, "sequencia": ["🔵", "🔴", "🔵", "🔵", "🔴", "🔴", "🔴", "🔵", "🔵"], "sinal": "🔴"},
    {"id": 56, "sequencia": ["🔴", "🔵", "🔴", "🔴", "🔵", "🔵", "🔵", "🔴", "🔴"], "sinal": "🔵"},
    {"id": 77, "sequencia": ["🔴", "🔵", "🔴", "🔴", "🔴", "🔴", "🔴", "🔵"], "sinal": "🔴"},
    {"id": 88, "sequencia": ["🔵", "🔴", "🔵", "🔵", "🔵", "🔵", "🔵", "🔴"], "sinal": "🔵"},
    {"id": 763, "sequencia": ["🔴", "🔴", "🔵", "🔵", "🔵", "🔴", "🔴"], "sinal": "🔵"},
    {"id": 390, "sequencia": ["🔵", "🔵", "🔴", "🔴", "🔴", "🔵", "🔵"], "sinal": "🔴"}
]

@retry(stop=stop_after_attempt(7), wait=wait_exponential(multiplier=1, min=4, max=60), retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)))
async def fetch_resultado():
    """Busca o resultado mais recente da API com retry e timeout aumentado."""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(API_URL, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status != 200:
                    return None, None, None, None
                data = await response.json()
                if 'data' not in data or 'result' not in data['data'] or 'outcome' not in data['data']['result']:
                    return None, None, None, None
                if 'id' not in data:
                    return None, None, None, None
                if data['data'].get('status') != 'Resolved':
                    return None, None, None, None
                resultado_id = data['id']
                outcome = data['data']['result']['outcome']
                player_score = data['data']['result'].get('playerDice', {}).get('score', 0)
                banker_score = data['data']['result'].get('bankerDice', {}).get('score', 0)
                if outcome not in OUTCOME_MAP:
                    return None, None, None, None
                resultado = OUTCOME_MAP[outcome]
                return resultado, resultado_id, player_score, banker_score
        except:
            return None, None, None, None

def verificar_tendencia(historico, sinal, tamanho_janela=8):
    if len(historico) < tamanho_janela:
        return True
    janela = historico[-tamanho_janela:]
    contagem = Counter(janela)
    total = contagem["🔴"] + contagem["🔵"]
    if total == 0:
        return True
    return True

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), retry=retry_if_exception_type(TelegramError))
async def enviar_sinal(sinal, padrao_id, resultado_id, sequencia):
    global ultima_mensagem_monitoramento
    try:
        if ultima_mensagem_monitoramento:
            try:
                await bot.delete_message(chat_id=CHAT_ID, message_id=ultima_mensagem_monitoramento)
            except TelegramError:
                pass
            ultima_mensagem_monitoramento = None
        if any(sinal["padrao_id"] == padrao_id for sinal in sinais_ativos):
            return
        sequencia_str = " ".join(sequencia)
        mensagem = f"""💡 CLEVER ANALISOU 💡
🧠 Tendência: {sinal}
🛡️ Proteja o TIE 🟡
🤑 VAI ENTRAR DINHEIRO🤑"""
        message = await bot.send_message(chat_id=CHAT_ID, text=mensagem)
        sinais_ativos.append({
            "sinal": sinal,
            "padrao_id": padrao_id,
            "resultado_id": resultado_id,
            "sequencia": sequencia,
            "enviado_em": asyncio.get_event_loop().time(),
            "gale_nivel": 0,
            "gale_message_id": None
        })
        return message.message_id
    except TelegramError as e:
        raise

async def enviar_placar():
    try:
        total_acertos = placar['ganhos_seguidos'] + placar['ganhos_gale1'] + placar['ganhos_gale2'] + placar['empates']
        total_sinais = total_acertos + placar['losses']
        precisao = (total_acertos / total_sinais * 100) if total_sinais > 0 else 0.0
        precisao = min(precisao, 100.0)
        mensagem_placar = f"""📊 Placar CLEVER
SG: {placar['ganhos_seguidos']}
1G: {placar['ganhos_gale1']}
2G: {placar['ganhos_gale2']}
E: {placar['empates']}
L: {placar['losses']}
Acertos: {total_acertos}
Erros: {placar['losses']}
Precisão: {precisao:.2f}%"""
        await bot.send_message(chat_id=CHAT_ID, text=mensagem_placar)
    except TelegramError:
        pass

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), retry=retry_if_exception_type(TelegramError))
async def enviar_resultado(resultado, player_score, banker_score, resultado_id):
    global rodadas_desde_erro, ultima_mensagem_monitoramento, detecao_pausada, placar
    try:
        for sinal_ativo in sinais_ativos[:]:
            if sinal_ativo["resultado_id"] != resultado_id:
                if resultado == sinal_ativo["sinal"] or resultado == "🟡":
                    if resultado == "🟡":
                        placar["empates"] += 1
                    if sinal_ativo["gale_nivel"] == 0:
                        placar["ganhos_seguidos"] += 1
                    elif sinal_ativo["gale_nivel"] == 1:
                        placar["ganhos_gale1"] += 1
                    else:
                        placar["ganhos_gale2"] += 1
                    if sinal_ativo["gale_message_id"]:
                        try:
                            await bot.delete_message(chat_id=CHAT_ID, message_id=sinal_ativo["gale_message_id"])
                        except TelegramError:
                            pass
                    mensagem_validacao = f"✅ ENTROU DINHEIRO\n🎲 Resultado: 🔵 {player_score} x 🔴 {banker_score}"
                    await bot.send_message(chat_id=CHAT_ID, text=mensagem_validacao)
                    await enviar_placar()
                    sinais_ativos.remove(sinal_ativo)
                    detecao_pausada = False
                else:
                    if sinal_ativo["gale_nivel"] == 0:
                        detecao_pausada = True
                        mensagem_gale = "🔄 Tentar 1º Gale"
                        message = await bot.send_message(chat_id=CHAT_ID, text=mensagem_gale)
                        sinal_ativo["gale_nivel"] = 1
                        sinal_ativo["gale_message_id"] = message.message_id
                        sinal_ativo["resultado_id"] = resultado_id
                    elif sinal_ativo["gale_nivel"] == 1:
                        detecao_pausada = True
                        mensagem_gale = "🔄 Tentar 2º Gale"
                        try:
                            await bot.delete_message(chat_id=CHAT_ID, message_id=sinal_ativo["gale_message_id"])
                        except TelegramError:
                            pass
                        message = await bot.send_message(chat_id=CHAT_ID, text=mensagem_gale)
                        sinal_ativo["gale_nivel"] = 2
                        sinal_ativo["gale_message_id"] = message.message_id
                        sinal_ativo["resultado_id"] = resultado_id
                    else:
                        placar["losses"] += 1
                        if sinal_ativo["gale_message_id"]:
                            try:
                                await bot.delete_message(chat_id=CHAT_ID, message_id=sinal_ativo["gale_message_id"])
                            except TelegramError:
                                pass
                        await bot.send_message(chat_id=CHAT_ID, text="❌ NÃO FOI DESSA❌")
                        await enviar_placar()
                        sinais_ativos.remove(sinal_ativo)
                        detecao_pausada = False
                ultima_mensagem_monitoramento = None
            elif asyncio.get_event_loop().time() - sinal_ativo["enviado_em"] > 300:
                if sinal_ativo["gale_message_id"]:
                    try:
                        await bot.delete_message(chat_id=CHAT_ID, message_id=sinal_ativo["gale_message_id"])
                    except TelegramError:
                        pass
                sinais_ativos.remove(sinal_ativo)
                detecao_pausada = False
    except TelegramError:
        pass

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), retry=retry_if_exception_type(TelegramError))
async def enviar_monitoramento():
    global ultima_mensagem_monitoramento
    while True:
        try:
            if not sinais_ativos:
                if ultima_mensagem_monitoramento:
                    try:
                        await bot.delete_message(chat_id=CHAT_ID, message_id=ultima_mensagem_monitoramento)
                    except TelegramError:
                        pass
                message = await bot.send_message(chat_id=CHAT_ID, text="🔎 Monitorando a mesa...")
                ultima_mensagem_monitoramento = message.message_id
            await asyncio.sleep(15)
        except TelegramError:
            await asyncio.sleep(15)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), retry=retry_if_exception_type(TelegramError))
async def enviar_relatorio():
    while True:
        try:
            total_acertos = placar['ganhos_seguidos'] + placar['ganhos_gale1'] + placar['ganhos_gale2'] + placar['empates']
            total_sinais = total_acertos + placar['losses']
            precisao = (total_acertos / total_sinais * 100) if total_sinais > 0 else 0.0
            precisao = min(precisao, 100.0)
            msg = f"""📈 Relatório CLEVER
SG: {placar['ganhos_seguidos']}
1G: {placar['ganhos_gale1']}
2G: {placar['ganhos_gale2']}
E: {placar['empates']}
L: {placar['losses']}
Acertos: {total_acertos}
Erros: {placar['losses']}
Precisão: {precisao:.2f}%"""
            await bot.send_message(chat_id=CHAT_ID, text=msg)
        except TelegramError:
            pass
        await asyncio.sleep(3600)

async def enviar_erro_telegram(erro_msg):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=f"❌ Erro detectado: {erro_msg}")
    except TelegramError:
        pass

async def main():
    global historico, ultimo_padrao_id, ultimo_resultado_id, rodadas_desde_erro, detecao_pausada
    asyncio.create_task(enviar_relatorio())
    asyncio.create_task(enviar_monitoramento())
    try:
        await bot.send_message(chat_id=CHAT_ID, text="🚀 Bot iniciado com sucesso!")
    except TelegramError:
        pass
    while True:
        try:
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
                        if not detecao_pausada and verificar_tendencia(historico, padrao["sinal"]):
                            await enviar_sinal(padrao["sinal"], padrao["id"], resultado_id, padrao["sequencia"])
                            ultimo_padrao_id = padrao["id"]
            await asyncio.sleep(2)
        except Exception as e:
            await enviar_erro_telegram(str(e))
            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Bot encerrado pelo usuário")
    except Exception as e:
        logging.error(f"Erro fatal no bot: {e}")
        asyncio.run(enviar_erro_telegram(f"Erro fatal no bot: {e}"))
