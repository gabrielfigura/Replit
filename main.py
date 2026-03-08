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

# ============================================================
# CONFIGURAÇÃO
# ============================================================
TELEGRAM_TOKEN = "7525707247:AAHLVwSdes_UlaVQ5TUo72q-4mMZXE8_lfE"
CHANNEL_ID = "-1003564529662"

API_URL = "https://api.signals-house.com/api/rounds"
API_PARAMS = {
    "gameId": "bacbo",
    "platformId": "evolution",
    "limit": 50
}

POLL_INTERVAL = 1          # 1s — captar resultado o mais rápido possível
MAX_HISTORY = 80
MAX_GALE = 2
SIGNAL_COOLDOWN_DURATION = 0  # zero cooldown — cada round pode gerar sinal

OUTCOME_MAP = {
    "Player": "🔵",
    "Banker": "🔴",
    "Tie":    "🟡",
    "player": "🔵",
    "banker": "🔴",
    "tie":    "🟡",
}

# ============================================================
# ESTADO GLOBAL
# ============================================================
historico: list[str] = []
last_round_id = None
sinal_pendente = None       # {"cor": str, "gale": int, "msg_id": int|None}
sinal_timestamp = 0.0

bot = Bot(token=TELEGRAM_TOKEN)
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")

# ============================================================
# API
# ============================================================
async def fetch_api(session: aiohttp.ClientSession):
    try:
        async with session.get(API_URL, params=API_PARAMS, timeout=aiohttp.ClientTimeout(total=5)) as r:
            if r.status == 200:
                return await r.json()
            logging.warning(f"API status {r.status}")
    except Exception as e:
        logging.error(f"Erro fetch: {e}")
    return None

# ============================================================
# 50 ESTRATÉGIAS — motor de votação ponderada
# ============================================================
def _last(h, n):
    return h[:n] if len(h) >= n else []

def e01(h):
    """Maioria simples últimos 3"""
    s = _last(h, 3)
    if not s: return {}
    c = Counter(s)
    top = c.most_common(1)[0]
    return {top[0]: 0.5} if top[1] >= 2 else {}

def e02(h):
    """Maioria últimos 5"""
    s = _last(h, 5)
    if not s: return {}
    c = Counter(s)
    top = c.most_common(1)[0]
    return {top[0]: 0.6} if top[1] >= 3 else {}

def e03(h):
    """Maioria últimos 7"""
    s = _last(h, 7)
    if not s: return {}
    c = Counter(s)
    top = c.most_common(1)[0]
    return {top[0]: 0.7} if top[1] >= 4 else {}

def e04(h):
    """Inversão — se últimos 3 iguais, aposta no oposto"""
    s = _last(h, 3)
    if len(s) == 3 and s[0] == s[1] == s[2]:
        opp = "🔴" if s[0] == "🔵" else "🔵"
        return {opp: 0.8}
    return {}

def e05(h):
    """Inversão forte — últimos 4 iguais"""
    s = _last(h, 4)
    if len(s) == 4 and len(set(s)) == 1:
        opp = "🔴" if s[0] == "🔵" else "🔵"
        return {opp: 1.0}
    return {}

def e06(h):
    """Padrão ABAB"""
    s = _last(h, 4)
    if len(s) == 4 and s[0] == s[2] and s[1] == s[3] and s[0] != s[1]:
        return {s[0]: 0.7}
    return {}

def e07(h):
    """Padrão AABB"""
    s = _last(h, 4)
    if len(s) == 4 and s[0] == s[1] and s[2] == s[3] and s[0] != s[2]:
        return {s[2]: 0.6}
    return {}

def e08(h):
    """Padrão AAB → A"""
    s = _last(h, 3)
    if len(s) == 3 and s[1] == s[2] and s[0] != s[1]:
        return {s[1]: 0.5}
    return {}

def e09(h):
    """Padrão ABB → A"""
    s = _last(h, 3)
    if len(s) == 3 and s[0] == s[1] and s[0] != s[2]:
        return {s[2]: 0.5}
    return {}

def e10(h):
    """Repetição do último"""
    s = _last(h, 1)
    if s:
        return {s[0]: 0.3}
    return {}

def e11(h):
    """Contra o último"""
    s = _last(h, 1)
    if s:
        opp = "🔴" if s[0] == "🔵" else "🔵"
        return {opp: 0.2}
    return {}

def e12(h):
    """Streak curta (2) continua"""
    s = _last(h, 2)
    if len(s) == 2 and s[0] == s[1]:
        return {s[0]: 0.6}
    return {}

def e13(h):
    """Alternância perfeita últimos 4"""
    s = _last(h, 4)
    if len(s) == 4:
        alt = all(s[i] != s[i+1] for i in range(3))
        if alt:
            opp = "🔴" if s[0] == "🔵" else "🔵"
            return {opp: 0.7}
    return {}

def e14(h):
    """Frequência relativa 10 — aposta no mais frequente"""
    s = _last(h, 10)
    if len(s) < 10: return {}
    c = Counter(s)
    az = c.get("🔵", 0)
    vm = c.get("🔴", 0)
    if az > vm + 2: return {"🔵": 0.5}
    if vm > az + 2: return {"🔴": 0.5}
    return {}

def e15(h):
    """Frequência relativa 10 — aposta no menos frequente (reversão)"""
    s = _last(h, 10)
    if len(s) < 10: return {}
    c = Counter(s)
    az = c.get("🔵", 0)
    vm = c.get("🔴", 0)
    if az > vm + 3: return {"🔴": 0.6}
    if vm > az + 3: return {"🔵": 0.6}
    return {}

def e16(h):
    """Proporção áurea — a cada ~8 rounds, espera inversão"""
    s = _last(h, 8)
    if len(s) < 8: return {}
    c = Counter(s)
    dom = c.most_common(1)[0]
    if dom[1] >= 6:
        opp = "🔴" if dom[0] == "🔵" else "🔵"
        return {opp: 0.8}
    return {}

def e17(h):
    """Fibonacci — posições 1,1,2,3,5 da história"""
    fibs = [0, 1, 1, 2, 4]
    vals = []
    for f in fibs:
        if f < len(h):
            vals.append(h[f])
    if len(vals) >= 4:
        c = Counter(vals)
        top = c.most_common(1)[0]
        if top[1] >= 3:
            return {top[0]: 0.6}
    return {}

def e18(h):
    """Entropia de Shannon — baixa entropia = tendência forte"""
    s = _last(h, 10)
    if len(s) < 10: return {}
    c = Counter(s)
    total = len(s)
    entropy = 0.0
    for v in c.values():
        p = v / total
        if p > 0:
            entropy -= p * math.log2(p)
    if entropy < 0.8:
        top = c.most_common(1)[0]
        return {top[0]: 0.9}
    return {}

def e19(h):
    """Entropia alta — mercado indeciso, não apostar"""
    s = _last(h, 10)
    if len(s) < 10: return {}
    c = Counter(s)
    total = len(s)
    entropy = 0.0
    for v in c.values():
        p = v / total
        if p > 0:
            entropy -= p * math.log2(p)
    if entropy > 0.95:
        return {"🔵": -0.3, "🔴": -0.3}
    return {}

def e20(h):
    """Média móvel 3 vs 7"""
    if len(h) < 7: return {}
    def avg(sl):
        return sum(1 if x == "🔵" else 0 for x in sl) / len(sl)
    ma3 = avg(h[:3])
    ma7 = avg(h[:7])
    if ma3 > ma7 + 0.2: return {"🔵": 0.6}
    if ma3 < ma7 - 0.2: return {"🔴": 0.6}
    return {}

def e21(h):
    """Média móvel 5 vs 15"""
    if len(h) < 15: return {}
    def avg(sl):
        return sum(1 if x == "🔵" else 0 for x in sl) / len(sl)
    ma5 = avg(h[:5])
    ma15 = avg(h[:15])
    if ma5 > ma15 + 0.15: return {"🔵": 0.5}
    if ma5 < ma15 - 0.15: return {"🔴": 0.5}
    return {}

def e22(h):
    """Detector de regime — streak vs chop"""
    s = _last(h, 10)
    if len(s) < 10: return {}
    changes = sum(1 for i in range(len(s)-1) if s[i] != s[i+1])
    if changes <= 3:
        return {s[0]: 0.7}
    if changes >= 7:
        opp = "🔴" if s[0] == "🔵" else "🔵"
        return {opp: 0.5}
    return {}

def e23(h):
    """Último empate seguido de cor dominante"""
    if "🟡" in h[:5]:
        idx = h[:5].index("🟡")
        after = [x for x in h[:idx] if x in ("🔵", "🔴")]
        if after:
            return {after[0]: 0.4}
    return {}

def e24(h):
    """Padrão ABA"""
    s = _last(h, 3)
    if len(s) == 3 and s[0] == s[2] and s[0] != s[1]:
        return {s[1]: 0.5}
    return {}

def e25(h):
    """Padrão ABBA"""
    s = _last(h, 4)
    if len(s) == 4 and s[0] == s[3] and s[1] == s[2] and s[0] != s[1]:
        return {s[0]: 0.6}
    return {}

def e26(h):
    """Padrão ABCBA (com empate)"""
    s = _last(h, 5)
    if len(s) == 5 and s[0] == s[4] and s[1] == s[3]:
        return {s[2]: 0.4}
    return {}

def e27(h):
    """Sequência crescente de streaks"""
    if len(h) < 8: return {}
    streaks = []
    cur = 1
    for i in range(1, min(len(h), 15)):
        if h[i] == h[i-1]:
            cur += 1
        else:
            streaks.append(cur)
            cur = 1
    streaks.append(cur)
    if len(streaks) >= 3 and streaks[0] > streaks[1] > streaks[2]:
        return {h[0]: 0.6}
    return {}

def e28(h):
    """Proporção 60/40 nos últimos 20"""
    s = _last(h, 20)
    if len(s) < 20: return {}
    c = Counter(s)
    az = c.get("🔵", 0)
    vm = c.get("🔴", 0)
    total = az + vm
    if total == 0: return {}
    if az / total >= 0.6: return {"🔵": 0.5}
    if vm / total >= 0.6: return {"🔴": 0.5}
    return {}

def e29(h):
    """Regressão à média — extremo nos últimos 5"""
    s = _last(h, 5)
    if len(s) < 5: return {}
    c = Counter(s)
    az = c.get("🔵", 0)
    vm = c.get("🔴", 0)
    if az >= 4: return {"🔴": 0.7}
    if vm >= 4: return {"🔵": 0.7}
    return {}

def e30(h):
    """Dupla confirmação — últimos 2 iguais E maioria 5"""
    s2 = _last(h, 2)
    s5 = _last(h, 5)
    if len(s2) < 2 or len(s5) < 5: return {}
    if s2[0] == s2[1]:
        c = Counter(s5)
        if c.get(s2[0], 0) >= 3:
            return {s2[0]: 0.8}
    return {}

def e31(h):
    """Tripla confirmação — streak 3 + maioria 7"""
    s3 = _last(h, 3)
    s7 = _last(h, 7)
    if len(s3) < 3 or len(s7) < 7: return {}
    if s3[0] == s3[1] == s3[2]:
        c = Counter(s7)
        if c.get(s3[0], 0) >= 5:
            return {s3[0]: 0.9}
    return {}

def e32(h):
    """Gap analysis — cor ausente há 3+ rounds"""
    s = _last(h, 5)
    if len(s) < 3: return {}
    cores_presentes = set(s[:3])
    if "🔵" not in cores_presentes: return {"🔵": 0.5}
    if "🔴" not in cores_presentes: return {"🔴": 0.5}
    return {}

def e33(h):
    """Cor ausente há 5+ rounds"""
    s = _last(h, 5)
    if len(s) < 5: return {}
    cores = set(s)
    if "🔵" not in cores: return {"🔵": 0.8}
    if "🔴" not in cores: return {"🔴": 0.8}
    return {}

def e34(h):
    """Hot hand — última cor ganhou 2 das últimas 3"""
    s = _last(h, 3)
    if len(s) < 3: return {}
    c = Counter(s)
    if c.get(s[0], 0) >= 2:
        return {s[0]: 0.5}
    return {}

def e35(h):
    """Gambler's fallacy inverso — apostar COM a tendência"""
    s = _last(h, 6)
    if len(s) < 6: return {}
    c = Counter(s)
    top = c.most_common(1)[0]
    if top[1] >= 4:
        return {top[0]: 0.4}
    return {}

def e36(h):
    """Ciclo de 4 — padrão se repete a cada 4"""
    if len(h) < 8: return {}
    if h[0] == h[4] and h[1] == h[5] and h[2] == h[6]:
        return {h[3]: 0.7}
    return {}

def e37(h):
    """Ciclo de 3"""
    if len(h) < 6: return {}
    if h[0] == h[3] and h[1] == h[4]:
        return {h[2]: 0.6}
    return {}

def e38(h):
    """Spike detector — mudança brusca após estabilidade"""
    s = _last(h, 6)
    if len(s) < 6: return {}
    if s[1] == s[2] == s[3] == s[4] == s[5] and s[0] != s[1]:
        return {s[0]: 0.6}
    return {}

def e39(h):
    """Padrão zigzag 5"""
    s = _last(h, 5)
    if len(s) < 5: return {}
    if all(s[i] != s[i+1] for i in range(4)):
        opp = "🔴" if s[0] == "🔵" else "🔵"
        return {opp: 0.6}
    return {}

def e40(h):
    """Correlação com posição par/ímpar"""
    if len(h) < 10: return {}
    pares = [h[i] for i in range(0, 10, 2)]
    c = Counter(pares)
    top = c.most_common(1)[0]
    if top[1] >= 4:
        return {top[0]: 0.4}
    return {}

def e41(h):
    """Run test — runs menor que esperado = tendência"""
    s = _last(h, 12)
    if len(s) < 12: return {}
    runs = 1
    for i in range(1, len(s)):
        if s[i] != s[i-1]:
            runs += 1
    expected = len(s) / 2 + 1
    if runs < expected - 2:
        return {s[0]: 0.7}
    if runs > expected + 2:
        opp = "🔴" if s[0] == "🔵" else "🔵"
        return {opp: 0.5}
    return {}

def e42(h):
    """Peso exponencial — resultados recentes valem mais"""
    if len(h) < 5: return {}
    score_az = 0.0
    score_vm = 0.0
    for i, v in enumerate(h[:8]):
        w = math.exp(-0.3 * i)
        if v == "🔵": score_az += w
        elif v == "🔴": score_vm += w
    if score_az > score_vm + 0.5: return {"🔵": 0.6}
    if score_vm > score_az + 0.5: return {"🔴": 0.6}
    return {}

def e43(h):
    """Momentum — aceleração da tendência"""
    if len(h) < 8: return {}
    def ratio(sl):
        c = Counter(sl)
        return c.get("🔵", 0) / max(len(sl), 1)
    r1 = ratio(h[:4])
    r2 = ratio(h[4:8])
    diff = r1 - r2
    if diff > 0.3: return {"🔵": 0.6}
    if diff < -0.3: return {"🔴": 0.6}
    return {}

def e44(h):
    """Padrão pós-empate — cor que vem após empate"""
    for i in range(1, min(len(h), 10)):
        if h[i] == "🟡" and i > 0:
            return {h[i-1]: 0.3}
    return {}

def e45(h):
    """Frequência de empates alta — mercado volátil"""
    s = _last(h, 10)
    if len(s) < 10: return {}
    ties = sum(1 for x in s if x == "🟡")
    if ties >= 3:
        return {"🔵": -0.2, "🔴": -0.2}
    return {}

def e46(h):
    """Distribuição binomial — desvio significativo"""
    s = _last(h, 20)
    if len(s) < 20: return {}
    non_tie = [x for x in s if x != "🟡"]
    if len(non_tie) < 15: return {}
    az = sum(1 for x in non_tie if x == "🔵")
    p = az / len(non_tie)
    if p > 0.65: return {"🔴": 0.7}
    if p < 0.35: return {"🔵": 0.7}
    return {}

def e47(h):
    """Cluster detection — 3+ mesma cor em janela de 4"""
    s = _last(h, 4)
    if len(s) < 4: return {}
    c = Counter(s)
    top = c.most_common(1)[0]
    if top[1] >= 3:
        return {top[0]: 0.5}
    return {}

def e48(h):
    """Padrão espelho — últimos 3 = inverso dos 3 anteriores"""
    if len(h) < 6: return {}
    def inv(c):
        return "🔴" if c == "🔵" else "🔵" if c == "🔴" else c
    if all(h[i] == inv(h[i+3]) for i in range(3)):
        return {inv(h[0]): 0.6}
    return {}

def e49(h):
    """Peso pela distância ao empate"""
    if len(h) < 5: return {}
    dist = None
    for i, v in enumerate(h):
        if v == "🟡":
            dist = i
            break
    if dist is not None and dist <= 3:
        non_tie = [x for x in h[:dist] if x != "🟡"]
        if non_tie:
            return {non_tie[0]: 0.4}
    return {}

def e50(h):
    """Consenso global — se 3+ estratégias anteriores concordam (meta)"""
    # Esta é processada separadamente no motor
    return {}

ESTRATEGIAS = [
    e01, e02, e03, e04, e05, e06, e07, e08, e09, e10,
    e11, e12, e13, e14, e15, e16, e17, e18, e19, e20,
    e21, e22, e23, e24, e25, e26, e27, e28, e29, e30,
    e31, e32, e33, e34, e35, e36, e37, e38, e39, e40,
    e41, e42, e43, e44, e45, e46, e47, e48, e49, e50,
]

# ============================================================
# MOTOR DE SINAIS
# ============================================================
def gerar_sinal_estrategia(h) -> str | None:
    peso = {"🔵": 0.0, "🔴": 0.0}

    for fn in ESTRATEGIAS:
        try:
            votos = fn(h)
            for cor, w in votos.items():
                if cor in peso:
                    peso[cor] += w
        except Exception:
            continue

    melhor = max(peso, key=peso.get)
    pior = min(peso, key=peso.get)

    if peso[melhor] >= 3.0 and (peso[melhor] - peso[pior]) >= 2.0:
        return melhor
    return None

# ============================================================
# TELEGRAM — envio imediato
# ============================================================
async def enviar_sinal(cor: str):
    global sinal_pendente, sinal_timestamp
    nome = "🔵 PLAYER" if cor == "🔵" else "🔴 BANKER"
    texto = (
        f"🎯 *SINAL BACBO*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"Entrada: *{nome}*\n"
        f"Proteção: Até Gale 2\n"
        f"━━━━━━━━━━━━━━━\n"
        f"⏳ *Aposte AGORA!*"
    )
    msg = await bot.send_message(
        chat_id=CHANNEL_ID, text=texto, parse_mode="Markdown"
    )
    sinal_pendente = {"cor": cor, "gale": 0, "msg_id": msg.message_id}
    sinal_timestamp = time.time()
    logging.info(f"📨 Sinal enviado: {nome}")

async def resolver_sinal(resultado: str):
    global sinal_pendente
    if not sinal_pendente:
        return

    cor_apostada = sinal_pendente["cor"]
    gale = sinal_pendente["gale"]
    msg_id = sinal_pendente["msg_id"]

    if resultado == cor_apostada:
        # ✅ WIN
        gale_txt = f" (Gale {gale})" if gale > 0 else ""
        texto = f"✅ *WIN{gale_txt}!*"
        sinal_pendente = None
    elif resultado == "🟡":
        # Empate — mantém sinal
        texto = "🟡 Empate — sinal mantido."
        return
    else:
        # ❌ LOSS ou GALE
        if gale < MAX_GALE:
            sinal_pendente["gale"] = gale + 1
            nome = "🔵 PLAYER" if cor_apostada == "🔵" else "🔴 BANKER"
            texto = (
                f"🔄 *GALE {gale + 1}*\n"
                f"Entrada: *{nome}*\n"
                f"⏳ *Aposte AGORA!*"
            )
            msg = await bot.send_message(
                chat_id=CHANNEL_ID, text=texto, parse_mode="Markdown"
            )
            sinal_pendente["msg_id"] = msg.message_id
            logging.info(f"🔄 Gale {gale + 1} enviado")
            return
        else:
            texto = f"❌ *LOSS (Gale {gale})*"
            sinal_pendente = None

    await bot.send_message(
        chat_id=CHANNEL_ID, text=texto, parse_mode="Markdown"
    )
    logging.info(f"Resultado: {texto}")

# ============================================================
# LOOP PRINCIPAL — polling rápido + envio imediato
# ============================================================
async def poll_loop():
    global historico, last_round_id, sinal_pendente

    logging.info("🚀 Bot iniciado — polling a cada 1s")

    async with aiohttp.ClientSession() as session:
        # Carga inicial do histórico
        data = await fetch_api(session)
        if data:
            items = data.get("data", [])
            for item in reversed(items):
                emoji = OUTCOME_MAP.get(item.get("result", ""))
                if emoji:
                    historico.append(emoji)
            historico = historico[-MAX_HISTORY:]
            if items:
                last_round_id = items[0].get("id")
            logging.info(f"📊 Histórico carregado: {len(historico)} rounds")

        # Loop contínuo
        while True:
            try:
                data = await fetch_api(session)
                if data:
                    items = data.get("data", [])
                    if items:
                        latest = items[0]
                        rid = latest.get("id")

                        if rid and rid != last_round_id:
                            last_round_id = rid
                            outcome_raw = latest.get("result", "")
                            emoji = OUTCOME_MAP.get(outcome_raw)

                            if emoji:
                                historico.insert(0, emoji)
                                historico = historico[:MAX_HISTORY]
                                logging.info(f"🎲 Novo resultado: {emoji} (id={rid})")

                                # 1) Resolver sinal pendente PRIMEIRO
                                if sinal_pendente:
                                    await resolver_sinal(emoji)

                                # 2) Gerar novo sinal IMEDIATAMENTE
                                if not sinal_pendente:
                                    sinal = gerar_sinal_estrategia(historico)
                                    if sinal:
                                        await enviar_sinal(sinal)

            except Exception as e:
                logging.error(f"Erro no loop: {e}")

            await asyncio.sleep(POLL_INTERVAL)

# ============================================================
# MAIN
# ============================================================
async def main():
    await poll_loop()

if __name__ == "__main__":
    asyncio.run(main())
