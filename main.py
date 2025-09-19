import asyncio
import aiohttp
import logging
import os
from telegram import Bot
from telegram.error import TelegramError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from collections import Counter

# Configurações do Bot
BOT_TOKEN = os.getenv("BOT_TOKEN", "7703975421:AAG-CG5Who2xs4NlevJqB5TNvjjzeUEDz8o")
CHAT_ID = os.getenv("CHAT_ID", "-1002859771274")
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
placar = {"✅": 0}
rodadas_desde_erro = 0  # Contador para cooldown após erro
ultima_mensagem_monitoramento = None  # Rastrear ID da mensagem de monitoramento
detecao_pausada = False  # Controle para pausar detecção de novos sinais

# Mapeamento de outcomes para emojis
OUTCOME_MAP = {
    "PlayerWon": "🔵",
    "BankerWon": "🔴",
    "Tie": "🟡"
}

# Padrões (corrigidos para remover duplicatas de id)
PADROES = [
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
    {"id": 31, "sequencia": ["🔴", "🔴", "🔴"], "sinal": "🔵"},
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
    {"id": 526, "sequencia": ["🔵", "🔵", "🔵", "🔴"], "sinal": "🔴"}
]

@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=4, max=30), retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)))
async def fetch_resultado():
    """Busca o resultado mais recente da API com retry e timeout aumentado."""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(API_URL, timeout=aiohttp.ClientTimeout(total=15)) as response:
                if response.status != 200:
                    logging.error(f"Erro na API: Status {response.status}, Resposta: {await response.text()}")
                    return None, None, None, None
                data = await response.json()
                logging.debug(f"Resposta da API: {data}")
                
                if 'data' not in data or 'result' not in data['data'] or 'outcome' not in data['data']['result']:
                    logging.error(f"Estrutura inválida na resposta: {data}")
                    return None, None, None, None
                if 'id' not in data:
                    logging.error(f"Chave 'id' não encontrada na resposta: {data}")
                    return None, None, None, None
                
                if data['data'].get('status') != 'Resolved':
                    logging.debug(f"Jogo não resolvido: Status {data['data'].get('status')}")
                    return None, None, None, None
                
                resultado_id = data['id']
                outcome = data['data']['result']['outcome']
                player_score = data['data']['result'].get('playerDice', {}).get('score', 0)
                banker_score = data['data']['result'].get('bankerDice', {}).get('score', 0)
                
                if outcome not in OUTCOME_MAP:
                    logging.error(f"Outcome inválido: {outcome}")
                    return None, None, None, None
                resultado = OUTCOME_MAP[outcome]
                
                return resultado, resultado_id, player_score, banker_score
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logging.error(f"Erro de conexão com a API: {e}")
            return None, None, None, None
        except ValueError as e:
            logging.error(f"Erro ao parsear JSON: {e}")
            return None, None, None, None
        except Exception as e:
            logging.error(f"Erro inesperado ao buscar resultado: {e}")
            return None, None, None, None

def verificar_tendencia(historico, sinal, tamanho_janela=8):
    """Verifica se o sinal está alinhado com a tendência dos últimos resultados."""
    if len(historico) < tamanho_janela:
        return True  # Não há histórico suficiente, aceitar o sinal
    janela = historico[-tamanho_janela:]
    contagem = Counter(janela)
    total = contagem["🔴"] + contagem["🔵"]  # Ignorar empates na contagem
    if total == 0:
        return True  # Sem resultados válidos, aceitar o sinal
    proporcao = contagem[sinal] / total
    logging.debug(f"Tendência: {sinal} aparece {contagem[sinal]}/{total} ({proporcao:.2%})")
    return proporcao >= 0.6  # Aceitar sinal se ele representa 60% ou mais

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), retry=retry_if_exception_type(TelegramError))
async def enviar_sinal(sinal, padrao_id, resultado_id, sequencia):
    """Envia uma mensagem de sinal ao Telegram com retry, incluindo a sequência de cores."""
    global ultima_mensagem_monitoramento
    try:
        # Apagar a última mensagem de monitoramento, se existir
        if ultima_mensagem_monitoramento:
            try:
                await bot.delete_message(chat_id=CHAT_ID, message_id=ultima_mensagem_monitoramento)
                logging.debug("Mensagem de monitoramento apagada antes de enviar sinal")
            except TelegramError as e:
                logging.debug(f"Erro ao apagar mensagem de monitoramento: {e}")
            ultima_mensagem_monitoramento = None

        # Verificar se já existe um sinal ativo com o mesmo padrão ID
        if any(sinal["padrao_id"] == padrao_id for sinal in sinais_ativos):
            logging.debug(f"Sinal com Padrão ID {padrao_id} já ativo, ignorando.")
            return

        sequencia_str = " ".join(sequencia)
        mensagem = f"""🎯 SINAL ENCONTRADO
Padrão ID: {padrao_id}
Sequência: {sequencia_str}
Entrar: {sinal}
Proteger o empate🟡
⏳ Aposte agora!"""
        message = await bot.send_message(chat_id=CHAT_ID, text=mensagem)
        logging.info(f"Sinal enviado: Padrão {padrao_id}, Sequência: {sequencia_str}, Sinal: {sinal}, Resultado ID: {resultado_id}")
        sinais_ativos.append({
            "sinal": sinal,
            "padrao_id": padrao_id,
            "resultado_id": resultado_id,
            "sequencia": sequencia,
            "enviado_em": asyncio.get_event_loop().time(),
            "gale_nivel": 0,  # Inicializa com aposta base
            "gale_message_id": None  # Para rastrear a mensagem de gale
        })
        return message.message_id
    except TelegramError as e:
        logging.error(f"Erro ao enviar sinal: {e}")
        raise

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), retry=retry_if_exception_type(TelegramError))
async def enviar_resultado(resultado, player_score, banker_score, resultado_id):
    """Envia a validação de cada sinal ao Telegram após o resultado da próxima rodada."""
    global rodadas_desde_erro, ultima_mensagem_monitoramento, detecao_pausada, placar
    try:
        for sinal_ativo in sinais_ativos[:]:
            # Validar apenas se o resultado é posterior ao sinal
            if sinal_ativo["resultado_id"] != resultado_id:
                resultado_texto = f"🎲 Resultado: "
                if resultado == "🟡":
                    resultado_texto += f"EMPATE: {player_score}:{banker_score}"
                else:
                    resultado_texto += f"AZUL: {player_score} VS VERMELHO: {banker_score}"

                sequencia_str = " ".join(sinal_ativo["sequencia"])
                # Considerar empate (🟡) como acerto
                if resultado == sinal_ativo["sinal"] or resultado == "🟡":
                    placar["✅"] += 1
                    # Apagar mensagem de gale, se existir
                    if sinal_ativo["gale_message_id"]:
                        try:
                            await bot.delete_message(chat_id=CHAT_ID, message_id=sinal_ativo["gale_message_id"])
                            logging.debug(f"Mensagem de gale apagada: ID {sinal_ativo['gale_message_id']}")
                        except TelegramError as e:
                            logging.debug(f"Erro ao apagar mensagem de gale: {e}")
                    # Enviar validação com resultados da rodada atual
                    mensagem_validacao = f"🤑ENTROU DINHEIRO🤑\n{resultado_texto}\n📊 Resultado do sinal (Padrão {sinal_ativo['padrao_id']} Sequência: {sequencia_str})\nPlacar: {placar['✅']}✅"
                    await bot.send_message(chat_id=CHAT_ID, text=mensagem_validacao)
                    logging.info(f"Validação enviada: Sinal {sinal_ativo['sinal']}, Resultado {resultado}, Resultado ID: {resultado_id}, Validação: {mensagem_validacao}")
                    sinais_ativos.remove(sinal_ativo)
                else:
                    if sinal_ativo["gale_nivel"] == 0:
                        # Primeira perda: pausar detecção e enviar mensagem de gale
                        detecao_pausada = True
                        mensagem_gale = "BORA GANHAR NO 1 GALE🎯"
                        message = await bot.send_message(chat_id=CHAT_ID, text=mensagem_gale)
                        sinal_ativo["gale_nivel"] = 1
                        sinal_ativo["gale_message_id"] = message.message_id
                        sinal_ativo["resultado_id"] = resultado_id  # Atualizar para esperar próximo resultado
                        logging.info(f"Mensagem de gale enviada: {mensagem_gale}, ID: {message.message_id}")
                    else:
                        # Verificar se o 1 gale acertou (mesma cor ou empate)
                        if resultado == sinal_ativo["sinal"] or resultado == "🟡":
                            placar["✅"] += 1
                            # Apagar mensagem de gale
                            if sinal_ativo["gale_message_id"]:
                                try:
                                    await bot.delete_message(chat_id=CHAT_ID, message_id=sinal_ativo["gale_message_id"])
                                    logging.debug(f"Mensagem de gale apagada: ID {sinal_ativo['gale_message_id']}")
                                except TelegramError as e:
                                    logging.debug(f"Erro ao apagar mensagem de gale: {e}")
                            # Enviar validação com resultados da rodada do 1 gale
                            mensagem_validacao = f"🤑ENTROU DINHEIRO🤑\n{resultado_texto}\n📊 Resultado do sinal (Padrão {sinal_ativo['padrao_id']} Sequência: {sequencia_str})\nPlacar: {placar['✅']}✅"
                            await bot.send_message(chat_id=CHAT_ID, text=mensagem_validacao)
                            logging.info(f"Validação enviada (1 Gale): Sinal {sinal_ativo['sinal']}, Resultado {resultado}, Resultado ID: {resultado_id}, Validação: {mensagem_validacao}")
                            sinais_ativos.remove(sinal_ativo)
                            detecao_pausada = False  # Retomar detecção após resolver o gale
                        else:
                            # Erro no 1 gale
                            if sinal_ativo["gale_message_id"]:
                                try:
                                    await bot.delete_message(chat_id=CHAT_ID, message_id=sinal_ativo["gale_message_id"])
                                    logging.debug(f"Mensagem de gale apagada: ID {sinal_ativo['gale_message_id']}")
                                except TelegramError as e:
                                    logging.debug(f"Erro ao apagar mensagem de gale: {e}")
                            placar["✅"] = 0  # Zerar o placar após erro no 1 gale
                            await bot.send_message(chat_id=CHAT_ID, text="NÃO FOI DESSA🤧")
                            logging.info(f"Validação enviada (Erro 1 Gale): Sinal {sinal_ativo['sinal']}, Resultado {resultado}, Resultado ID: {resultado_id}")
                            sinais_ativos.remove(sinal_ativo)
                            detecao_pausada = False  # Retomar detecção após erro

                # Após validação, retomar monitoramento
                ultima_mensagem_monitoramento = None
            # Limpar sinais obsoletos (mais de 5 minutos sem validação)
            elif asyncio.get_event_loop().time() - sinal_ativo["enviado_em"] > 300:
                logging.warning(f"Sinal obsoleto removido: Padrão {sinal_ativo['padrao_id']}, Resultado ID: {sinal_ativo['resultado_id']}")
                # Apagar mensagem de gale, se existir
                if sinal_ativo["gale_message_id"]:
                    try:
                        await bot.delete_message(chat_id=CHAT_ID, message_id=sinal_ativo["gale_message_id"])
                        logging.debug(f"Mensagem de gale obsoleta apagada: ID {sinal_ativo['gale_message_id']}")
                    except TelegramError as e:
                        logging.debug(f"Erro ao apagar mensagem de gale obsoleta: {e}")
                sinais_ativos.remove(sinal_ativo)
                detecao_pausada = False  # Retomar detecção se sinal obsoleto
    except TelegramError as e:
        logging.error(f"Erro ao enviar resultado: {e}")

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), retry=retry_if_exception_type(TelegramError))
async def enviar_monitoramento():
    """Envia mensagem de monitoramento a cada 15 segundos, apagando a anterior."""
    global ultima_mensagem_monitoramento
    while True:
        try:
            if not sinais_ativos:  # Só enviar se não houver sinais ativos
                # Apagar a mensagem anterior, se existir
                if ultima_mensagem_monitoramento:
                    try:
                        await bot.delete_message(chat_id=CHAT_ID, message_id=ultima_mensagem_monitoramento)
                        logging.debug("Mensagem de monitoramento anterior apagada")
                    except TelegramError as e:
                        logging.debug(f"Erro ao apagar mensagem de monitoramento: {e}")
                
                # Enviar nova mensagem
                message = await bot.send_message(chat_id=CHAT_ID, text="MONITORANDO A MESA…🤌")
                ultima_mensagem_monitoramento = message.message_id
                logging.debug(f"Mensagem de monitoramento enviada: ID {ultima_mensagem_monitoramento}")
            else:
                logging.debug("Monitoramento pausado: Sinal ativo pendente")
        except TelegramError as e:
            logging.error(f"Erro ao enviar monitoramento: {e}")
        await asyncio.sleep(15)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), retry=retry_if_exception_type(TelegramError))
async def enviar_relatorio():
    """Envia um relatório periódico com o placar."""
    while True:
        try:
            msg = f"📈 Relatório: Bot em operação\nPlacar: {placar['✅']}✅"
            await bot.send_message(chat_id=CHAT_ID, text=msg)
            logging.info(f"Relatório enviado: {msg}")
        except TelegramError as e:
            logging.error(f"Erro ao enviar relatório: {e}")
        await asyncio.sleep(3600)

async def main():
    """Loop principal do bot com reconexão."""
    global historico, ultimo_padrao_id, ultimo_resultado_id, rodadas_desde_erro, detecao_pausada
    asyncio.create_task(enviar_relatorio())
    asyncio.create_task(enviar_monitoramento())

    while True:
        try:
            resultado, resultado_id, player_score, banker_score = await fetch_resultado()
            if not resultado or not resultado_id:
                await asyncio.sleep(2)  # Reduzido de 5 para 2 segundos
                continue

            if ultimo_resultado_id is None or resultado_id != ultimo_resultado_id:
                ultimo_resultado_id = resultado_id
                historico.append(resultado)
                historico = historico[-25:]  # Mantém os últimos 25 resultados
                logging.info(f"Histórico atualizado: {historico} (ID: {resultado_id})")

                # Incrementar contador de rodadas desde o último erro
                rodadas_desde_erro += 1

                # Verifica se há sinais ativos para validar
                await enviar_resultado(resultado, player_score, banker_score, resultado_id)

                # Detecta padrão e envia sinal, apenas se detecção não estiver pausada
                if not detecao_pausada:  # Removido rodadas_desde_erro >= 3
                    padroes_ordenados = sorted(PADROES, key=lambda x: len(x["sequencia"]), reverse=True)
                    for padrao in padroes_ordenados:
                        seq = padrao["sequencia"]
                        # Ignorar sinais após empate, a menos que o padrão tenha 5 ou mais resultados
                        if len(historico) >= 1 and historico[-1] == "🟡" and len(seq) < 5:
                            logging.debug(f"Sinal ignorado: Último resultado é empate e padrão {padrao['id']} tem menos de 5 resultados")
                            continue
                        if (len(historico) >= len(seq) and 
                            historico[-len(seq):] == seq and 
                            padrao["id"] != ultimo_padrao_id and 
                            verificar_tendencia(historico, padrao["sinal"]) and
                            not any(sinal["padrao_id"] == padrao["id"] for sinal in sinais_ativos)):
                            await enviar_sinal(sinal=padrao["sinal"], padrao_id=padrao["id"], resultado_id=resultado_id, sequencia=seq)
                            ultimo_padrao_id = padrao["id"]
                            break

                if len(historico) >= 5:
                    ultimo_padrao_id = None

            else:
                logging.debug(f"Resultado repetido ignorado: ID {resultado_id}")

            await asyncio.sleep(2)  # Reduzido de 5 para 2 segundos
        except Exception as e:
            logging.error(f"Erro no loop principal: {e}")
            await asyncio.sleep(10)

if __name__ == "__main__":
    try:
        asyncio.run(main())
