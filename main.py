import asyncio
import aiohttp
import logging
from telegram import Bot
from telegram.error import TelegramError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from collections import Counter

# ==================== CONFIGURAÇÕES ====================
BOT_TOKEN = "7703975421:AAG-CG5Who2xs4NlevJqB5TNvjjzeUEDz8o"
CHAT_ID = "-1002859771274"
API_URL = "https://api.casinoscores.com/svc-evolution-game-events/api/bacbo/latest"

bot = Bot(token=BOT_TOKEN)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ==================== ESTADO DO BOT ====================
historico = []
ultimo_padrao_id = None
ultimo_resultado_id = None
sinais_ativos = []
placar = {"ganhos_seguidos": 0, "ganhos_gale1": 0, "ganhos_gale2": 0, "losses": 0, "empates": 0}
ultima_mensagem_monitoramento = None
detecao_pausada = False

# ==================== MAPEAMENTOS CORRETOS ====================
OUTCOME_MAP = {
    "PlayerWon": "blue",
    "BankerWon": "red",
    "Tie": "yellow"
}

# ==================== PADRÕES (com emojis corretos) ====================
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

# ==================== FUNÇÕES ====================
@retry(stop=stop_after_attempt(7), wait=wait_exponential(multiplier=1, min=4, max=60))
async def fetch_resultado():
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(API_URL, timeout=30) as resp:
                if resp.status != 200:
                    return None, None, None, None
                data = await resp.json()
                if data.get('data', {}).get('status') != 'Resolved':
                    return None, None, None, None
                outcome = data['data']['result']['outcome']
                resultado = OUTCOME_MAP.get(outcome)
                if not resultado:
                    return None, None, None, None
                return resultado, data['id'], data['data']['result'].get('playerDice', {}).get('score', 0), data['data']['result'].get('bankerDice', {}).get('score', 0)
        except:
            return None, None, None, None

async def enviar_sinal(sinal, padrao_id, resultado_id, sequencia):
    global ultima_mensagem_monitoramento
    if ultima_mensagem_monitoramento:
        try:
            await bot.delete_message(CHAT_ID, ultima_mensagem_monitoramento)
        except:
            pass
        ultima_mensagem_monitoramento = None

    if any(s["padrao_id"] == padrao_id for s in sinais_ativos):
        return

    msg = f"""🎭CLEVER ANALISOU🎭
🧌Tendência: {sinal}
Proteja o TIE 🟡
💵VAI ENTRAR DINHEIRO💵"""
    message = await bot.send_message(CHAT_ID, msg)
    sinais_ativos.append({
        "sinal": sinal,
        "padrao_id": padrao_id,
        "resultado_id": resultado_id,
        "sequencia": sequencia,
        "enviado_em": asyncio.get_event_loop().time(),
        "gale_nivel": 0,
        "gale_message_id": None
    })

async def enviar_placar():
    total_acertos = placar['ganhos_seguidos'] + placar['ganhos_gale1'] + placar['ganhos_gale2'] + placar['empates']
    total_sinais = total_acertos + placar['losses']
    precisao = (total_acertos / total_sinais * 100) if total_sinais > 0 else 0
    msg = f"""🎭CLEVER PERFORMANCE🎭
✅SEM GALE: {placar['ganhos_seguidos']}
✅GALE 1: {placar['ganhos_gale1']}
✅GALE 2: {placar['ganhos_gale2']}
🟡EMPATES: {placar['empates']}
✅ACERTOS: {total_acertos}
❌ERROS: {placar['losses']}
❌PRECISÃO: {precisao:.1f}%
O SEGREDO É A DISCIPLINA ❤️"""
    await bot.send_message(CHAT_ID, msg)

async def enviar_resultado(resultado, player_score, banker_score, resultado_id):
    global detecao_pausada

    for sinal_ativo in sinais_ativos[:]:
        if sinal_ativo["resultado_id"] == resultado_id:
            continue

        # ACERTO (ou empate)
        if resultado == sinal_ativo["sinal"] or resultado == "yellow":
            if resultado == "yellow":
                placar["empates"] += 1

            nivel = sinal_ativo["gale_nivel"]
            if nivel == 0:
                placar["ganhos_seguidos"] += 1
                texto_gale = "🔁GALE 0 (Entrada)"
            elif nivel == 1:
                placar["ganhos_gale1"] += 1
                texto_gale = "🔁1º GALE"
            else:
                placar["ganhos_gale2"] += 1
                texto_gale = "🔁2º GALE"

            if sinal_ativo["gale_message_id"]:
                try:
                    await bot.delete_message(CHAT_ID, sinal_ativo["gale_message_id"])
                except:
                    pass

            await bot.send_message(CHAT_ID, f"""💵ENTROU DINHEIRO💵 
{texto_gale}
📊Resultado: 🔵 {player_score} × 🔴 {banker_score}""")
            await enviar_placar()
            sinais_ativos.remove(sinal_ativo)
            detecao_pausada = False

        else:
            # ERRO → GALE
            if sinal_ativo["gale_nivel"] == 0:
                detecao_pausada = True
                msg = await bot.send_message(CHAT_ID, "🔁Tentar 1º Gale")
                sinal_ativo["gale_nivel"] = 1
                sinal_ativo["gale_message_id"] = msg.message_id
                sinal_ativo["resultado_id"] = resultado_id

            elif sinal_ativo["gale_nivel"] == 1:
                detecao_pausada = True
                try:
                    await bot.delete_message(CHAT_ID, sinal_ativo["gale_message_id"])
                except:
                    pass
                msg = await bot.send_message(CHAT_ID, "🔁Tentar 2º Gale")
                sinal_ativo["gale_nivel"] = 2
                sinal_ativo["gale_message_id"] = msg.message_id
                sinal_ativo["resultado_id"] = resultado_id

            else:
                # LOSS FINAL
                placar["losses"] += 1
                if sinal_ativo["gale_message_id"]:
                    try:
                        await bot.delete_message(CHAT_ID, sinal_ativo["gale_message_id"])
                    except:
                        pass
                await bot.send_message(CHAT_ID, "❌NÃO FOI DESSA❌")
                await enviar_placar()
                sinais_ativos.remove(sinal_ativo)
                detecao_pausada = False

async def monitoramento():
    global ultima_mensagem_monitoramento
    while True:
        if not sinais_ativos and ultima_mensagem_monitoramento is None:
            msg = await bot.send_message(CHAT_ID, "Monitorando a mesa...")
            ultima_mensagem_monitoramento = msg.message_id
        elif sinais_ativos and ultima_mensagem_monitoramento:
            try:
                await bot.delete_message(CHAT_ID, ultima_mensagem_monitoramento)
            except:
                pass
            ultima_mensagem_monitoramento = None
        await asyncio.sleep(15)

async def main():
    asyncio.create_task(monitoramento())
    )
    await bot.send_message(CHAT_ID, "Bot iniciado com sucesso!")

    while True:
        try:
            resultado, resultado_id, p_score, b_score = await fetch_resultado()
            if not resultado or resultado_id == ultimo_resultado_id:
                await asyncio.sleep(2)
                continue

            global ultimo_resultado_id
            ultimo_resultado_id = resultado_id
            historico.append(resultado)
            if len(historico) > 100:
                historico.pop(0)

            await enviar_resultado(resultado, p_score, b_score, resultado_id)

            for padrao in PADROES:
                if (len(historico) >= len(padrao["sequencia"]) and
                    historico[-len(padrao["sequencia"]):] == padrao["sequencia"] and
                    padrao["id"] != ultimo_padrao_id and
                    not detecao_pausada):
                    await enviar_sinal(padrao["sinal"], padrao["id"], resultado_id, padrao["sequencia"])
                    ultimo_padrao_id = padrao["id"]
                    break  # evita enviar o mesmo padrão várias vezes

            await asyncio.sleep(2)
        except Exception as e:
            print("Erro:", e)
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
