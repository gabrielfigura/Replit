import asyncio
import aiohttp
import logging
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackQueryHandler
from telegram.error import TelegramError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from collections import Counter

# Configurações do Bot
BOT_TOKEN = "7703975421:AAG-CG5Who2xs4NlevJqB5TNvjjzeUEDz8o"
CHAT_ID = "-1002859771274"
API_URL = "https://api-cs.casino.org/svc-evolution-game-events/api/bacbo/latest"  # Nova API

# Inicializar o bot e a aplicação
bot = Bot(token=BOT_TOKEN)
application = Application.builder().token(BOT_TOKEN).build()

# Configuração de logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")

# Histórico e estado
historico = []
empates_historico = []
ultimo_padrao_id = None
ultimo_resultado_id = None
sinais_ativos = []
placar = {
    "ganhos_seguidos": 0,
    "ganhos_gale1": 0,
    "ganhos_gale2": 0,
    "losses": 0,
    "empates": 0
}
ultima_mensagem_monitoramento = None
detecao_pausada = False
aguardando_validacao = False

# Mapeamento de outcomes para emojis
OUTCOME_MAP = {
    "PlayerWon": "🔵",
    "BankerWon": "🔴",
    "Tie": "🟡"
}

# Padrões (mantidos iguais)
PADROES = [
    # ... (todos os seus 100 padrões permanecem exatamente iguais)
    # Não vou repetir aqui para economizar espaço, mas mantenha exatamente como estavam
    { "id": 1, "sequencia": ["🔵", "🔴", "🔵", "🔴"], "sinal": "🔵" },
    # ... até o id 100
    { "id": 100, "sequencia": ["🔴", "🔵", "🔵"], "sinal": "🔵" }
]

@retry(stop=stop_after_attempt(7), wait=wait_exponential(multiplier=1, min=4, max=60),
       retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)))
async def fetch_resultado():
    """Busca o resultado mais recente da nova API."""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(API_URL, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status != 200:
                    logging.warning(f"API retornou status {response.status}")
                    return None, None, None, None
                
                data = await response.json()
                
                # Verificações de estrutura
                if not data or 'id' not in data or 'data' not in data:
                    return None, None, None, None
                
                game_data = data['data']
                if game_data.get('status') != 'Resolved':
                    return None, None, None, None
                
                result = game_data.get('result', {})
                if not result or 'outcome' not in result:
                    return None, None, None, None
                
                resultado_id = data['id']
                outcome = result['outcome']
                
                if outcome not in OUTCOME_MAP:
                    return None, None, None, None
                
                player_score = result.get('playerDice', {}).get('score', 0)
                banker_score = result.get('bankerDice', {}).get('score', 0)
                
                resultado = OUTCOME_MAP[outcome]
                
                logging.debug(f"Novo resultado: {resultado} (ID: {resultado_id}) - Player: {player_score} x Banker: {banker_score}")
                return resultado, resultado_id, player_score, banker_score
                
        except Exception as e:
            logging.error(f"Erro ao buscar resultado: {e}")
            return None, None, None, None

def verificar_tendencia(historico, sinal, tamanho_janela=8):
    if len(historico) < tamanho_janela:
        return True
    janela = historico[-tamanho_janela:]
    contagem = Counter(janela)
    total = contagem["🔴"] + contagem["🔵"]
    if total == 0:
        return True
    return True  # Sua lógica original sempre retornava True

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10),
       retry=retry_if_exception_type(TelegramError))
async def enviar_sinal(sinal, padrao_id, resultado_id, sequencia):
    global ultima_mensagem_monitoramento, aguardando_validacao
    try:
        if ultima_mensagem_monitoramento:
            try:
                await bot.delete_message(chat_id=CHAT_ID, message_id=ultima_mensagem_monitoramento)
            except TelegramError:
                pass
            ultima_mensagem_monitoramento = None

        if aguardando_validacao or sinais_ativos:
            logging.info(f"Sinal bloqueado: aguardando validação ou sinal ativo (ID: {padrao_id})")
            return False

        sequencia_str = " ".join(sequencia)
        mensagem = f"""💡 CLEVER ANALISOU 💡
🧠 APOSTA EM: {sinal}
🛡️ Proteja o TIE 🟡
🤑 VAI ENTRAR DINHEIRO 🤑
⬇️ENTRA NA COMUNIDADE DO WHATSAPP ⬇️
https://chat.whatsapp.com/D61X4xCSDyk02srBHqBYXq"""

        keyboard = [[InlineKeyboardButton("EMPATES 🟡", callback_data="mostrar_empates")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        message = await bot.send_message(chat_id=CHAT_ID, text=mensagem, reply_markup=reply_markup)

        sinais_ativos.append({
            "sinal": sinal,
            "padrao_id": padrao_id,
            "resultado_id": resultado_id,
            "sequencia": sequencia,
            "enviado_em": asyncio.get_event_loop().time(),
            "gale_nivel": 0,
            "gale_message_id": None
        })
        aguardando_validacao = True
        logging.info(f"Sinal enviado para padrão {padrao_id}: {sinal}")
        return message.message_id

    except TelegramError as e:
        logging.error(f"Erro ao enviar sinal: {e}")
        raise

async def mostrar_empates(update, context):
    try:
        if not empates_historico:
            await update.callback_query.answer("Nenhum empate registrado ainda.")
            return
        empates_str = "\n".join([
            f"Empate {i+1}: 🟡 (🔵 {e['player_score']} x 🔴 {e['banker_score']})"
            for i, e in enumerate(empates_historico[-20:])  # Mostra apenas os últimos 20
        ])
        mensagem = f"📊 Histórico de Empates 🟡 (últimos {len(empates_historico[-20:])})\n\n{empates_str}"
        await update.callback_query.message.reply_text(mensagem)
        await update.callback_query.answer()
    except TelegramError as e:
        logging.error(f"Erro ao mostrar empates: {e}")
        await update.callback_query.answer("Erro ao exibir empates.")

async def resetar_placar():
    global placar
    placar = {
        "ganhos_seguidos": 0,
        "ganhos_gale1": 0,
        "ganhos_gale2": 0,
        "losses": 0,
        "empates": 0
    }
    try:
        await bot.send_message(chat_id=CHAT_ID, text="🔄 Placar resetado após 10 erros! Começando do zero.")
        await enviar_placar()
    except TelegramError:
        pass

async def enviar_placar():
    try:
        total_acertos = placar['ganhos_seguidos'] + placar['ganhos_gale1'] + placar['ganhos_gale2'] + placar['empates']
        total_sinais = total_acertos + placar['losses']
        precisao = (total_acertos / total_sinais * 100) if total_sinais > 0 else 0.0
        precisao = min(precisao, 100.0)
        mensagem_placar = f"""🚀 CLEVER PERFORMANCE 🚀
✅SEM GALE: {placar['ganhos_seguidos']}
🔁GALE 1: {placar['ganhos_gale1']}
🔁GALE 2: {placar['ganhos_gale2']}
🟡EMPATES: {placar['empates']}
🎯ACERTOS: {total_acertos}
❌ERROS: {placar['losses']}
🔥PRECISÃO: {precisao:.2f}%"""
        await bot.send_message(chat_id=CHAT_ID, text=mensagem_placar)
    except TelegramError:
        pass

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10),
       retry=retry_if_exception_type(TelegramError))
async def enviar_resultado(resultado, player_score, banker_score, resultado_id):
    global ultima_mensagem_monitoramento, detecao_pausada, placar, ultimo_padrao_id, aguardando_validacao, empates_historico

    try:
        # Armazena empate no histórico
        if resultado == "🟡":
            empates_historico.append({"player_score": player_score, "banker_score": banker_score})
            if len(empates_historico) > 50:
                empates_historico.pop(0)

        # Processa sinais ativos
        for sinal_ativo in sinais_ativos[:]:
            if sinal_ativo["resultado_id"] == resultado_id:
                continue  # Já processado

            if resultado == sinal_ativo["sinal"] or resultado == "🟡":
                # Acertou
                if resultado == "🟡":
                    placar["empates"] += 1
                if sinal_ativo["gale_nivel"] == 0:
                    placar["ganhos_seguidos"] += 1
                elif sinal_ativo["gale_nivel"] == 1:
                    placar["ganhos_gale1"] += 1
                else:
                    placar["ganhos_gale2"] += 1

                if sinal_ativo.get("gale_message_id"):
                    try:
                        await bot.delete_message(chat_id=CHAT_ID, message_id=sinal_ativo["gale_message_id"])
                    except TelegramError:
                        pass

                mensagem_validacao = f" 🤡ENTROU DINHEIRO🤡\n🎲 Resultado: 🔵 {player_score} x 🔴 {banker_score}"
                await bot.send_message(chat_id=CHAT_ID, text=mensagem_validacao)
                await enviar_placar()

                ultimo_padrao_id = None
                aguardando_validacao = False
                sinais_ativos.remove(sinal_ativo)
                detecao_pausada = False
                logging.info(f"Sinal GREEN - Padrão {sinal_ativo['padrao_id']}")

            else:
                # Errou - entra em gale
                if sinal_ativo["gale_nivel"] < 2:
                    detecao_pausada = True
                    nivel = sinal_ativo["gale_nivel"] + 1
                    mensagem_gale = f"🔄 Tentar {nivel}º Gale"
                    if sinal_ativo.get("gale_message_id"):
                        try:
                            await bot.delete_message(chat_id=CHAT_ID, message_id=sinal_ativo["gale_message_id"])
                        except:
                            pass
                    msg = await bot.send_message(chat_id=CHAT_ID, text=mensagem_gale)
                    sinal_ativo["gale_nivel"] = nivel
                    sinal_ativo["gale_message_id"] = msg.message_id
                    sinal_ativo["resultado_id"] = resultado_id
                else:
                    # Perdeu após 2 gales
                    placar["losses"] += 1
                    if sinal_ativo.get("gale_message_id"):
                        try:
                            await bot.delete_message(chat_id=CHAT_ID, message_id=sinal_ativo["gale_message_id"])
                        except:
                            pass
                    await bot.send_message(chat_id=CHAT_ID, text="❌ NÃO FOI DESSA VEZ ❌")
                    await enviar_placar()
                    if placar["losses"] >= 10:
                        await resetar_placar()
                    ultimo_padrao_id = None
                    aguardando_validacao = False
                    sinais_ativos.remove(sinal_ativo)
                    detecao_pausada = False
                    logging.info(f"Sinal RED - Padrão {sinal_ativo['padrao_id']}")

            # Atualiza ID do resultado processado
            sinal_ativo["resultado_id"] = resultado_id

        if not sinais_ativos:
            aguardando_validacao = False

    except TelegramError as e:
        logging.error(f"Erro ao processar resultado: {e}")

async def enviar_monitoramento():
    global ultima_mensagem_monitoramento
    while True:
        try:
            if not sinais_ativos and not detecao_pausada:
                if ultima_mensagem_monitoramento:
                    try:
                        await bot.delete_message(chat_id=CHAT_ID, message_id=ultima_mensagem_monitoramento)
                    except:
                        pass
                msg = await bot.send_message(chat_id=CHAT_ID, text="🔎 MONITORANDO A MESA…")
                ultima_mensagem_monitoramento = msg.message_id
            await asyncio.sleep(15)
        except:
            await asyncio.sleep(15)

async def enviar_relatorio():
    while True:
        await asyncio.sleep(3600)
        await enviar_placar()

async def main():
    global historico, ultimo_padrao_id, ultimo_resultado_id, detecao_pausada, aguardando_validacao

    application.add_handler(CallbackQueryHandler(mostrar_empates, pattern="mostrar_empates"))
    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    asyncio.create_task(enviar_monitoramento())
    asyncio.create_task(enviar_relatorio())

    try:
        await bot.send_message(chat_id=CHAT_ID, text="🚀 Bot iniciado com sucesso! (Nova API)")
    except:
        pass

    while True:
        try:
            resultado, resultado_id, player_score, banker_score = await fetch_resultado()
            if not resultado or not resultado_id:
                await asyncio.sleep(3)
                CONTINUE

            if resultado_id == ultimo_resultado_id:
                await asyncio.sleep(2)
                continue

            ultimo_resultado_id = resultado_id
            historico.append(resultado)
            if len(historico) > 50:
                historico.pop(0)

            await enviar_resultado(resultado, player_score, banker_score, resultado_id)

            if not detecao_pausada and not aguardando_validacao and not sinais_ativos:
                for padrao in PADROES:
                    seq_len = len(padrao["sequencia"])
                    if len(historico) >= seq_len and historico[-seq_len:] == padrao["sequencia"]:
                        if padrao["id"] != ultimo_padrao_id and verificar_tendencia(historico, padrao["sinal"]):
                            enviado = await enviar_sinal(padrao["sinal"], padrao["id"], resultado_id, padrao["sequencia"])
                            if enviado:
                                ultimo_padrao_id = padrao["id"]
                                break

            await asyncio.sleep(2)

        except Exception as e:
            logging.error(f"Erro no loop principal: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Bot encerrado pelo usuário")
    except Exception as e:
        logging.error(f"Erro fatal: {e}")
