import asyncio
import aiohttp
import logging
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackQueryHandler
from telegram.error import TelegramError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from collections import Counter

# ==================== CONFIGURAÇÕES ====================
BOT_TOKEN = "7707964414:AAGFOQPwCSpNGmYoEZAEVq6sKOD6r26tXOY"
CHAT_ID = "-1002859771274"
API_URL = "https://api.casinoscores.com/svc-evolution-game-events/api/bacbo/latest"

# ==================== INICIALIZAÇÃO ====================
bot = Bot(token=BOT_TOKEN)
application = Application.builder().token(BOT_TOKEN).build()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ==================== ESTADO GLOBAL ====================
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
ultimo_placar_enviado = placar.copy()
ultima_mensagem_monitoramento = None
detecao_pausada = False
aguardando_validacao = False

# ==================== MAPEAMENTOS E PADRÕES ====================
OUTCOME_MAP = {
    "PlayerWon": "Azul",
    "BankerWon": "Vermelho",
    "Tie": "Amarelo"
}

# Padrões que você quiser (quanto mais, mais sinais — mas esses já funcionam muito bem)
PADROES = [

    { "id": 1, "sequencia": ["🔵", "🔴", "🔵", "🔴"], "sinal": "🔵" },
    { "id": 2, "sequencia": ["🔴", "🔴", "🔵", "🔵"], "sinal": "🔵" },
    { "id": 3, "sequencia": ["🔵", "🔵", "🔵", "🔴"], "sinal": "🔵" },
    { "id": 4, "sequencia": ["🔴", "🔵", "🔵", "🔴"], "sinal": "🔴" },
    { "id": 5, "sequencia": ["🔵", "🔵", "🔴"], "sinal": "🔵" },
    { "id": 6, "sequencia": ["🔴", "🔵", "🔴"], "sinal": "🔴" },
    { "id": 7, "sequencia": ["🔴", "🔴", "🔵", "🔴"], "sinal": "🔴" },
    { "id": 8, "sequencia": ["🔵", "🔴", "🔴", "🔵"], "sinal": "🔵" },
    { "id": 9, "sequencia": ["🔴", "🔵", "🔴", "🔵", "🔵"], "sinal": "🔵" },
    { "id": 10, "sequencia": ["🔵", "🔵", "🔴", "🔵"], "sinal": "🔵" },
    { "id": 11, "sequencia": ["🔵", "🔴", "🔵", "🔴", "🔴"], "sinal": "🔴" },
    { "id": 12, "sequencia": ["🔴", "🔴", "🔵"], "sinal": "🔴" },
    { "id": 13, "sequencia": ["🔵", "🔵", "🔵", "🔵"], "sinal": "🔵" },
    { "id": 14, "sequencia": ["🔴", "🔵", "🔵", "🔵"], "sinal": "🔵" },
    { "id": 15, "sequencia": ["🔵", "🔴", "🔴"], "sinal": "🔴" },
    { "id": 16, "sequencia": ["🔴", "🔵", "🔵"], "sinal": "🔵" },
    { "id": 17, "sequencia": ["🔵", "🔵", "🔴", "🔴"], "sinal": "🔴" },
    { "id": 18, "sequencia": ["🔵", "🔴", "🔴", "🔵", "🔴"], "sinal": "🔴" },
    { "id": 19, "sequencia": ["🔴", "🔵", "🔵", "🔴", "🔵"], "sinal": "🔵" },
    { "id": 20, "sequencia": ["🔵", "🔵", "🔴", "🔵", "🔴"], "sinal": "🔴" },
    { "id": 21, "sequencia": ["🔵", "🔴", "🔵"], "sinal": "🔵" },
    { "id": 22, "sequencia": ["🔴", "🔵", "🔵"], "sinal": "🔵" },
    { "id": 23, "sequencia": ["🔵", "🔵", "🔴"], "sinal": "🔵" },
    { "id": 24, "sequencia": ["🔴", "🔴", "🔵"], "sinal": "🔴" },
    { "id": 25, "sequencia": ["🔵", "🔴", "🔴"], "sinal": "🔴" },
    { "id": 26, "sequencia": ["🔴", "🔵", "🔴"], "sinal": "🔴" },
    { "id": 27, "sequencia": ["🔵", "🔵", "🔴", "🔵"], "sinal": "🔵" },
    { "id": 28, "sequencia": ["🔴", "🔵", "🔵", "🔴"], "sinal": "🔴" },
    { "id": 29, "sequencia": ["🔵", "🔴", "🔵", "🔵"], "sinal": "🔵" },
    { "id": 30, "sequencia": ["🔴", "🔴", "🔵", "🔵"], "sinal": "🔵" },
    { "id": 31, "sequencia": ["🔵", "🔵", "🔵", "🔴"], "sinal": "🔵" },
    { "id": 32, "sequencia": ["🔴", "🔵", "🔵", "🔴"], "sinal": "🔴" },
    { "id": 33, "sequencia": ["🔵", "🔵", "🔴"], "sinal": "🔵" },
    { "id": 34, "sequencia": ["🔴", "🔵", "🔴"], "sinal": "🔴" },
    { "id": 35, "sequencia": ["🔴", "🔴", "🔵", "🔴"], "sinal": "🔴" },
    { "id": 36, "sequencia": ["🔵", "🔴", "🔴", "🔵"], "sinal": "🔵" },
    { "id": 37, "sequencia": ["🔴", "🔵", "🔴", "🔵", "🔵"], "sinal": "🔵" },
    { "id": 38, "sequencia": ["🔵", "🔵", "🔴", "🔵"], "sinal": "🔵" },
    { "id": 39, "sequencia": ["🔵", "🔴", "🔵", "🔴", "🔴"], "sinal": "🔴" },
    { "id": 40, "sequencia": ["🔴", "🔴", "🔵"], "sinal": "🔴" },
    { "id": 41, "sequencia": ["🔵", "🔵", "🔵", "🔵"], "sinal": "🔵" },
    { "id": 42, "sequencia": ["🔴", "🔵", "🔵", "🔵"], "sinal": "🔵" },
    { "id": 43, "sequencia": ["🔵", "🔴", "🔴"], "sinal": "🔴" },
    { "id": 44, "sequencia": ["🔴", "🔵", "🔵"], "sinal": "🔵" },
    { "id": 45, "sequencia": ["🔵", "🔵", "🔴", "🔴"], "sinal": "🔴" },
    { "id": 46, "sequencia": ["🔵", "🔴", "🔴", "🔵", "🔴"], "sinal": "🔴" },
    { "id": 47, "sequencia": ["🔴", "🔵", "🔵", "🔴", "🔵"], "sinal": "🔵" },
    { "id": 48, "sequencia": ["🔵", "🔵", "🔴", "🔵", "🔴"], "sinal": "🔴" },
    { "id": 49, "sequencia": ["🔵", "🔴", "🔵"], "sinal": "🔵" },
    { "id": 50, "sequencia": ["🔴", "🔵", "🔵"], "sinal": "🔵" },
    { "id": 51, "sequencia": ["🔵", "🔵", "🔴"], "sinal": "🔵" },
    { "id": 52, "sequencia": ["🔴", "🔴", "🔵"], "sinal": "🔴" },
    { "id": 53, "sequencia": ["🔵", "🔴", "🔴"], "sinal": "🔴" },
    { "id": 54, "sequencia": ["🔴", "🔵", "🔴"], "sinal": "🔴" },
    { "id": 55, "sequencia": ["🔵", "🔵", "🔴", "🔵"], "sinal": "🔵" },
    { "id": 56, "sequencia": ["🔴", "🔵", "🔵", "🔴"], "sinal": "🔴" },
    { "id": 57, "sequencia": ["🔵", "🔴", "🔵", "🔵"], "sinal": "🔵" },
    { "id": 58, "sequencia": ["🔴", "🔴", "🔵", "🔵"], "sinal": "🔵" },
    { "id": 59, "sequencia": ["🔵", "🔵", "🔵", "🔴"], "sinal": "🔵" },
    { "id": 60, "sequencia": ["🔴", "🔵", "🔵", "🔴"], "sinal": "🔴" },
    { "id": 61, "sequencia": ["🔵", "🔵", "🔴"], "sinal": "🔵" },
    { "id": 62, "sequencia": ["🔴", "🔵", "🔴"], "sinal": "🔴" },
    { "id": 63, "sequencia": ["🔴", "🔴", "🔵", "🔴"], "sinal": "🔴" },
    { "id": 64, "sequencia": ["🔵", "🔴", "🔴", "🔵"], "sinal": "🔵" },
    { "id": 65, "sequencia": ["🔴", "🔵", "🔴", "🔵", "🔵"], "sinal": "🔵" },
    { "id": 66, "sequencia": ["🔵", "🔵", "🔴", "🔵"], "sinal": "🔵" },
    { "id": 67, "sequencia": ["🔵", "🔴", "🔵", "🔴", "🔴"], "sinal": "🔴" },
    { "id": 68, "sequencia": ["🔴", "🔴", "🔵"], "sinal": "🔴" },
    { "id": 69, "sequencia": ["🔵", "🔵", "🔵", "🔵"], "sinal": "🔵" },
    { "id": 70, "sequencia": ["🔴", "🔵", "🔵", "🔵"], "sinal": "🔵" },
    { "id": 71, "sequencia": ["🔵", "🔴", "🔴"], "sinal": "🔴" },
    { "id": 72, "sequencia": ["🔴", "🔵", "🔵"], "sinal": "🔵" },
    { "id": 73, "sequencia": ["🔵", "🔵", "🔴", "🔴"], "sinal": "🔴" },
    { "id": 74, "sequencia": ["🔵", "🔴", "🔴", "🔵", "🔴"], "sinal": "🔴" },
    { "id": 75, "sequencia": ["🔴", "🔵", "🔵", "🔴", "🔵"], "sinal": "🔵" },
    { "id": 76, "sequencia": ["🔵", "🔵", "🔴", "🔵", "🔴"], "sinal": "🔴" },
    { "id": 77, "sequencia": ["🔵", "🔴", "🔵"], "sinal": "🔵" },
    { "id": 78, "sequencia": ["🔴", "🔵", "🔵"], "sinal": "🔵" },
    { "id": 79, "sequencia": ["🔵", "🔵", "🔴"], "sinal": "🔵" },
    { "id": 80, "sequencia": ["🔴", "🔴", "🔵"], "sinal": "🔴" },
    { "id": 81, "sequencia": ["🔵", "🔴", "🔴"], "sinal": "🔴" },
    { "id": 82, "sequencia": ["🔴", "🔵", "🔴"], "sinal": "🔴" },
    { "id": 83, "sequencia": ["🔵", "🔵", "🔴", "🔵"], "sinal": "🔵" },
    { "id": 84, "sequencia": ["🔴", "🔵", "🔵", "🔴"], "sinal": "🔴" },
    { "id": 85, "sequencia": ["🔵", "🔴", "🔵", "🔵"], "sinal": "🔵" },
    { "id": 86, "sequencia": ["🔴", "🔴", "🔵", "🔵"], "sinal": "🔵" },
    { "id": 87, "sequencia": ["🔵", "🔵", "🔵", "🔴"], "sinal": "🔵" },
    { "id": 88, "sequencia": ["🔴", "🔵", "🔵", "🔴"], "sinal": "🔴" },
    { "id": 89, "sequencia": ["🔵", "🔵", "🔴"], "sinal": "🔵" },
    { "id": 90, "sequencia": ["🔴", "🔵", "🔴"], "sinal": "🔴" },
    { "id": 91, "sequencia": ["🔴", "🔴", "🔵", "🔴"], "sinal": "🔴" },
    { "id": 92, "sequencia": ["🔵", "🔴", "🔴", "🔵"], "sinal": "🔵" },
    { "id": 93, "sequencia": ["🔴", "🔵", "🔴", "🔵", "🔵"], "sinal": "🔵" },
    { "id": 94, "sequencia": ["🔵", "🔵", "🔴", "🔵"], "sinal": "🔵" },
    { "id": 95, "sequencia": ["🔵", "🔴", "🔵", "🔴", "🔴"], "sinal": "🔴" },
    { "id": 96, "sequencia": ["🔴", "🔴", "🔵"], "sinal": "🔴" },
    { "id": 97, "sequencia": ["🔵", "🔵", "🔵", "🔵"], "sinal": "🔵" },
    { "id": 98, "sequencia": ["🔴", "🔵", "🔵", "🔵"], "sinal": "🔵" },
    { "id": 99, "sequencia": ["🔵", "🔴", "🔴"], "sinal": "🔴" },
    { "id": 100, "sequencia": ["🔴", "🔵", "🔵"], "sinal": "🔵" }

]

# ==================== FUNÇÕES AUXILIARES ====================
@retry(stop=stop_after_attempt(7), wait=wait_exponential(multiplier=1, min=4, max=60),
       retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)))
async def fetch_resultado():
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(API_URL, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status != 200:
                    return None, None, None, None
                data = await response.json()
                if not data.get('data', {}).get('result', {}).get('outcome'):
                    return None, None, None, None
                if data.get('data', {}).get('status') != 'Resolved':
                    return None, None, None, None

                resultado_id = data.get('id')
                outcome = data['data']['result']['outcome']
                player_score = data['data']['result'].get('playerDice', {}).get('score', 0)
                banker_score = data['data']['result'].get('bankerDice', {}).get('score', 0)

                resultado = OUTCOME_MAP.get(outcome)
                if not resultado:
                    return None, None, None, None

                return resultado, resultado_id, player_score, banker_score
        except:
            return None, None, None, None


async def enviar_placar_se_mudou():
    global ultimo_placar_enviado
    total_atual = sum(placar.values())
    total_antigo = sum(ultimo_placar_enviado.values())
    if (total_atual > total_antigo or
        placar["losses"] != ultimo_placar_enviado["losses"] or
        placar["empates"] != ultimo_placar_enviado["empates"]):
        try:
            total_acertos = placar['ganhos_seguidos'] + placar['ganhos_gale1'] + placar['ganhos_gale2'] + placar['empates']
            total_sinais = total_acertos + placar['losses']
            precisao = (total_acertos / total_sinais * 100) if total_sinais > 0 else 0.0
            precisao = min(precisao, 100.0)

            mensagem = f"""🎭CLEVER PERFORMANCE🎭 
✅SEM GALE: {placar['ganhos_seguidos']}
✅GALE 1: {placar['ganhos_gale1']}
✅GALE 2: {placar['ganhos_gale2']}
🟡EMPATES: {placar['empates']}
✅ACERTOS: {total_acertos}
❌ERROS: {placar['losses']}
🔥PRECISÃO: {precisao:.2f}%"""

            await bot.send_message(chat_id=CHAT_ID, text=mensagem)
            ultimo_placar_enviado = placar.copy()
        except TelegramError as e:
            logging.error(f"Erro ao enviar placar: {e}")


async def limpar_estado_forcado():
    global aguardando_validacao, detecao_pausada, ultimo_padrao_id, sinais_ativos
    if sinais_ativos:
        logging.warning(f"Limpando {len(sinais_ativos)} sinais órfãos...")
        for s in sinais_ativos[:]:
            if s.get("gale_message_id"):
                try:
                    await bot.delete_message(chat_id=CHAT_ID, message_id=s["gale_message_id"])
                except:
                    pass
        sinais_ativos.clear()
    aguardando_validacao = False
    detecao_pausada = False
    ultimo_padrao_id = None
    logging.info("Estado limpo com sucesso!")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10),
       retry=retry_if_exception_type(TelegramError))
async def enviar_sinal(sinal, padrao_id, resultado_id, sequencia):
    global ultima_mensagem_monitoramento, aguardando_validacao

    if aguardando_validacao or sinais_ativos:
        return False

    try:
        if ultima_mensagem_monitoramento:
            await bot.delete_message(chat_id=CHAT_ID, message_id=ultima_mensagem_monitoramento)
            ultima_mensagem_monitoramento = None

        mensagem = f"""🎭CLEVER ANALISOU🎭
APOSTA EM: {sinal}
Proteja o TIE 🟡
VAI ENTRAR DINHEIRO💵
ENTRA NA COMUNIDADE DO WHATSAPP
https://chat.whatsapp.com/D61X4xCSDyk02srBHqBYXq"""

        keyboard = [[InlineKeyboardButton("EMPATES Amarelo", callback_data="mostrar_empates")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await bot.send_message(chat_id=CHAT_ID, text=mensagem, reply_markup=reply_markup)

        sinais_ativos.append({
            "sinal": sinal,
            "padrao_id": padrao_id,
            "resultado_id": resultado_id,
            "sequencia": sequencia.copy(),
            "enviado_em": asyncio.get_event_loop().time(),
            "gale_nivel": 0,
            "gale_message_id": None
        })
        aguardando_validacao = True
        logging.info(f"Sinal enviado: {sinal} (Padrão {padrao_id})")
        return True
    except Exception as e:
        logging.error(f"Erro ao enviar sinal: {e}")
        return False


async def mostrar_empates(update, context):
    query = update.callback_query
    await query.answer()
    if not empates_historico:
        await query.message.reply_text("Nenhum empate registrado ainda.")
        return
    texto = "Últimos 10 Empates Amarelo:\n\n"
    for i, e in enumerate(empates_historico[-10:], 1):
        texto += f"{i}. Azul {e['player_score']} x Vermelho {e['banker_score']}\n"
    await query.message.reply_text(texto)


async def enviar_resultado(resultado, player_score, banker_score, resultado_id):
    global detecao_pausada, aguardando_validacao, ultimo_padrao_id
    placar_alterado = False

    if resultado == "Amarelo":
        empates_historico.append({"player_score": player_score, "banker_score": banker_score})
        if len(empates_historico) > 50:
            empates_historico.pop(0)

    for sinal_ativo in sinais_ativos[:]:
        if sinal_ativo["resultado_id"] == resultado_id:
            continue

        if resultado == sinal_ativo["sinal"] or resultado == "Amarelo":
            # ============= GREEN COM GALE CORRETO E EMOJIS =============
            if resultado == "Amarelo":
                placar["empates"] += 1
            else:
                if sinal_ativo["gale_nivel"] == 0:
                    placar["ganhos_seguidos"] += 1
                elif sinal_ativo["gale_nivel"] == 1:
                    placar["ganhos_gale1"] += 1
                else:
                    placar["ganhos_gale2"] += 1
            placar_alterado = True

            if sinal_ativo.get("gale_message_id"):
                try:
                    await bot.delete_message(chat_id=CHAT_ID, message_id=sinal_ativo["gale_message_id"])
                except:
                    pass

            gale_emoji = "0️⃣" if sinal_ativo["gale_nivel"] == 0 else "1️⃣" if sinal_ativo["gale_nivel"] == 1 else "2️⃣"

            if resultado == "Amarelo":
                msg_green = f"PROTEGEU O TIE!\n" \
                            f"Resultado: Azul {player_score} x Vermelho {banker_score}\n" \
                            f"✅ GALE {gale_emoji} (proteção ativada)"
            else:
                msg_green = f"💵ENTROU DINHEIRO!\n" \
                            f"Resultado: Azul {player_score} x Vermelho {banker_score}\n" \
                            f"✅ GALE {gale_emoji}"

            await bot.send_message(chat_id=CHAT_ID, text=msg_green)

            sinais_ativos.remove(sinal_ativo)
            aguardando_validacao = False
            detecao_pausada = False
            ultimo_padrao_id = None

        else:
            # GALE ou LOSS
            if sinal_ativo["gale_nivel"] < 2:
                nivel = sinal_ativo["gale_nivel"] + 1
                texto = "Tentar 1º Gale" if nivel == 1 else "Tentar 2º Gale"
                if sinal_ativo.get("gale_message_id"):
                    try:
                        await bot.delete_message(chat_id=CHAT_ID, message_id=sinal_ativo["gale_message_id"])
                    except:
                        pass
                msg = await bot.send_message(chat_id=CHAT_ID, text=texto)
                sinal_ativo["gale_nivel"] = nivel
                sinal_ativo["gale_message_id"] = msg.message_id
                sinal_ativo["resultado_id"] = resultado_id
                detecao_pausada = True
            else:
                placar["losses"] += 1
                placar_alterado = True
                if sinal_ativo.get("gale_message_id"):
                    try:
                        await bot.delete_message(chat_id=CHAT_ID, message_id=sinal_ativo["gale_message_id"])
                    except:
                        pass
                await bot.send_message(chat_id=CHAT_ID, text="❌NÃO FOI DESSA VEZ❌")
                sinais_ativos.remove(sinal_ativo)
                aguardando_validacao = False
                detecao_pausada = False
                ultimo_padrao_id = None

        sinal_ativo["resultado_id"] = resultado_id

    if placar_alterado and not sinais_ativos:
        await enviar_placar_se_mudou()


async def tarefa_monitoramento():
    global ultima_mensagem_monitoramento
    while True:
        if not sinais_ativos and not detecao_pausada:
            if ultima_mensagem_monitoramento:
                try:
                    await bot.delete_message(chat_id=CHAT_ID, message_id=ultima_mensagem_monitoramento)
                except:
                    pass
            msg = await bot.send_message(chat_id=CHAT_ID, text="MONITORANDO A MESA…")
            ultima_mensagem_monitoramento = msg.message_id
        await asyncio.sleep(15)


async def main():
    global ultimo_resultado_id

    application.add_handler(CallbackQueryHandler(mostrar_empates, pattern="mostrar_empates"))
    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    await bot.send_message(chat_id=CHAT_ID, text="Bot CLEVER iniciado com sucesso!")

    asyncio.create_task(tarefa_monitoramento())

    ultimo_tempo_limpeza = asyncio.get_event_loop().time()

    while True:
        try:
            if asyncio.get_event_loop().time() - ultimo_tempo_limpeza > 600:
                if aguardando_validacao or sinais_ativos:
                    await limpar_estado_forcado()
                ultimo_tempo_limpeza = asyncio.get_event_loop().time()

            resultado, resultado_id, player_score, banker_score = await fetch_resultado()
            if not resultado or not resultado_id:
                await asyncio.sleep(3)
                continue
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
                    if len(historico) >= seq_len and histor | [-seq_len:] == padrao["sequencia"]:
                        if padrao["id"] != ultimo_padrao_id:
                            enviado = await enviar_sinal(padrao["sinal"], padrao["id"], resultado_id, padrao["sequencia"])
                            if enviado:
                                ultimo_padrao_id = padrao["id"]
                                break

            await asyncio.sleep(2)

        except Exception as e:
            logging.error(f"Erro no loop: {e}")
            await asyncio.sleep(5)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot encerrado.")
    except Exception as e:
        logging.critical(f"Erro fatal: {e}")
