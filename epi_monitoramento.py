"""Regras de associação e confirmação, independentes da câmera e dos modelos."""

import math
import re
import unicodedata
from dataclasses import dataclass

from queda_temporal import AnaliseTemporal

EPIS = {
    "capacete": ("capacete", "helmet", "hardhat", "hard_hat", "hard hat"),
    "colete": ("colete", "vest", "safety_vest", "safety vest"),
    "oculos": ("oculos", "óculos", "goggles", "safety glasses", "safety goggles"),
    "luvas": ("luvas", "glove", "gloves"),
    "mascara": ("mascara", "máscara", "mask", "face mask"),
}


def normalizar_nome(nome):
    texto = unicodedata.normalize("NFKD", str(nome)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", texto.lower()).strip("_")


def identificar_epi(nome):
    nome = normalizar_nome(nome)
    for item, aliases in EPIS.items():
        if nome in {normalizar_nome(alias) for alias in aliases}:
            return item
    return None  # NO-Hardhat e similares nunca contam como presença.


def identificar_ausencia(nome):
    nome = normalizar_nome(nome)
    for prefixo in ('no_', 'without_', 'sem_'):
        if nome.startswith(prefixo):
            resto = nome[len(prefixo):]
            if resto == 'goggle':
                resto = 'goggles'
            return identificar_epi(resto)
    return None


def iou(a, b):
    inter = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0, min(a[3], b[3]) - max(a[1], b[1])
    )
    area_a = max(0, a[2] - a[0]) * max(0, a[3] - a[1])
    area_b = max(0, b[2] - b[0]) * max(0, b[3] - b[1])
    return inter / max(area_a + area_b - inter, 1)


@dataclass
class Pessoa:
    caixa: tuple
    visto: float
    velocidade: tuple = (0.0, 0.0)
    ambiguo: bool = False


class RastreadorPessoas:
    """IDs temporários com associação um-para-um; não identifica funcionários."""

    def __init__(self, tolerancia=2.0):
        self.tolerancia = tolerancia
        self.pessoas = {}
        self.proximo_id = 1

    def atualizar(self, caixas, agora):
        self.pessoas = {
            chave: pessoa for chave, pessoa in self.pessoas.items()
            if agora - pessoa.visto <= self.tolerancia
        }
        pares = []
        candidatos = {}
        for indice, caixa in enumerate(caixas):
            for pessoa_id, pessoa in self.pessoas.items():
                dt = max(0, min(agora - pessoa.visto, 1.0))
                vx, vy = pessoa.velocidade
                prevista = tuple(v + (vx if i % 2 == 0 else vy) * dt for i, v in enumerate(pessoa.caixa))
                escala = max(pessoa.caixa[3] - pessoa.caixa[1], caixa[3] - caixa[1], 1)
                distancia = math.hypot((caixa[0] + caixa[2] - prevista[0] - prevista[2]) / 2,
                                      (caixa[1] + caixa[3] - prevista[1] - prevista[3]) / 2) / escala
                sobreposicao = iou(caixa, prevista)
                if sobreposicao >= .15 or distancia < .35:
                    score = sobreposicao + .35 * max(0, 1 - distancia)
                    pares.append((score, indice, pessoa_id))
                    candidatos.setdefault(indice, []).append(score)
        ids = {}
        usados = set()
        for _, indice, pessoa_id in sorted(pares, reverse=True):
            if indice not in ids and pessoa_id not in usados:
                ids[indice] = pessoa_id
                usados.add(pessoa_id)
        for indice, caixa in enumerate(caixas):
            anterior = self.pessoas.get(ids.get(indice))
            if indice not in ids:
                ids[indice] = self.proximo_id
                self.proximo_id += 1
            velocidade = (0.0, 0.0)
            if anterior and 0 < agora - anterior.visto <= self.tolerancia:
                dt = agora - anterior.visto
                velocidade = tuple((caixa[i] + caixa[i + 2] - anterior.caixa[i] - anterior.caixa[i + 2]) / (2 * dt) for i in (0, 1))
            scores = sorted(candidatos.get(indice, []), reverse=True)
            ambiguo = len(scores) > 1 and scores[0] - scores[1] < .15
            # Caixas quase coincidentes não fornecem uma identidade confiável.
            ambiguo |= any(j != indice and iou(caixa, outra) > .6 for j, outra in enumerate(caixas))
            self.pessoas[ids[indice]] = Pessoa(tuple(caixa), agora, velocidade, ambiguo)
        return [ids[indice] for indice in range(len(caixas))]


@dataclass
class Observacao:
    inicio: float
    ultima: float
    quadros: int = 1


class ConfirmadorAlertas:
    def __init__(self, intervalo=60, tolerancia=2.0):
        self.intervalo = intervalo
        self.tolerancia = tolerancia
        self.observacoes = {}
        self.alertados = {}
        self.avisados_continuos = set()

    def observar(self, chave, sinal, agora, duracao):
        if not sinal:
            self.observacoes.pop(chave, None)
            self.avisados_continuos.discard(chave)
            return False
        estado = self.observacoes.get(chave)
        if estado is None or agora < estado.ultima or agora - estado.ultima > self.tolerancia:
            estado = Observacao(agora, agora)
            self.observacoes[chave] = estado
        else:
            if agora > estado.ultima:
                estado.ultima = agora
                estado.quadros += 1
        return estado.quadros >= 3 and agora - estado.inicio >= duracao

    def pode_alertar(self, chave, agora):
        if chave in self.avisados_continuos:
            return False
        ultimo = self.alertados.get(chave)
        return ultimo is None or agora - ultimo >= self.intervalo

    def marcar_alerta(self, chaves, agora):
        for chave in chaves:
            self.alertados[chave] = agora
            if chave in self.observacoes:
                self.avisados_continuos.add(chave)

    def limpar_ausentes(self, presentes, existentes):
        # Uma pessoa perdida interrompe a confirmação, mesmo que o ID sobreviva.
        self.observacoes = {
            chave: valor for chave, valor in self.observacoes.items()
            if chave[0] in presentes
        }
        self.alertados = {
            chave: valor for chave, valor in self.alertados.items()
            if chave[0] in existentes
        }
        self.avisados_continuos.intersection_update(self.observacoes)


def ponto_visivel(pontos, indice, confianca=0.6):
    ponto = pontos.get(indice)
    return ponto is not None and ponto[2] >= confianca


def enriquecer_rosto(pontos, faces):
    """Normaliza marcos de um único rosto no mesmo recorte usado pela pose."""
    pontos = dict(pontos)
    pontos["_rosto_avaliado"] = True
    pontos["_rosto_ok"] = len(faces) == 1
    if len(faces) == 1:
        face = faces[0]
        if "caixa" in face:
            pontos["_rosto_caixa"] = face["caixa"]
        for indice, chave in ((2, "olho_esquerdo"), (5, "olho_direito"), (0, "nariz")):
            x, y = face[chave]
            pontos[indice] = (x, y, face["confianca"])
    return pontos


def referencia_olhos(caixa, pontos):
    if pontos.get("_rosto_avaliado") and not pontos.get("_rosto_ok"):
        return None
    if not all(ponto_visivel(pontos, p) for p in (2, 5)):
        return None
    x1, y1, x2, y2 = caixa
    largura, altura = x2 - x1, y2 - y1
    esquerdo, direito = pontos[2], pontos[5]
    ex, ey = x1 + esquerdo[0] * largura, y1 + esquerdo[1] * altura
    dx, dy = x1 + direito[0] * largura, y1 + direito[1] * altura
    distancia = math.hypot(ex - dx, ey - dy)
    if distancia < 12:
        return None
    return ((ex + dx) / 2, (ey + dy) / 2, distancia)


def regiao_verificavel(item, caixa, pontos, tamanho):
    largura, altura = caixa[2] - caixa[0], caixa[3] - caixa[1]
    h_quadro, w_quadro = tamanho[:2]
    if item == "oculos":
        referencia = referencia_olhos(caixa, pontos)
        if referencia is None or not ponto_visivel(pontos, 0):
            return False
        cx, cy, distancia = referencia
        nariz_x = caixa[0] + pontos[0][0] * largura
        rosto = pontos.get("_rosto_caixa")
        if rosto is not None:
            fx1, fy1, fx2, fy2 = rosto
            # Marcos de um rosto cortado ou quase de perfil podem ser estimados,
            # mesmo com alta confiança do detector de rosto.
            if min(fx1, fy1) < 0 or max(fx2, fy2) > 1:
                return False
            if distancia < (fx2 - fx1) * largura * 0.28:
                return False
        # Perfil, olhos minúsculos ou região cortada não comprovam ausência.
        return (
            altura >= 100 and largura >= 60
            and abs(nariz_x - cx) <= distancia * 0.6
            and abs(pontos[2][1] - pontos[5][1]) * altura <= distancia * 0.6
            and cx - distancia * 1.2 > 2 and cx + distancia * 1.2 < w_quadro - 2
            and cy - distancia * 0.6 > 2 and cy + distancia * 0.8 < h_quadro - 2
        )
    if altura < 160 or largura < 60:
        return False
    if caixa[0] <= 2 or caixa[1] <= 2 or caixa[2] >= w_quadro - 2 or caixa[3] >= h_quadro - 2:
        return False
    if item == "colete":
        return all(ponto_visivel(pontos, p) for p in (11, 12, 23, 24))
    if item == "capacete":
        return ponto_visivel(pontos, 0) and all(ponto_visivel(pontos, p) for p in (11, 12))
    if item == "mascara":
        if not all(ponto_visivel(pontos, p) for p in (0, 2, 5)):
            return False
        return abs(pontos[2][0] - pontos[5][0]) * largura >= 12
    if item == "luvas":
        return altura >= 220 and all(ponto_visivel(pontos, p) for p in (15, 16, 19, 20))
    return False


def associar_epis(pessoas, deteccoes, ausencia=False):
    """Cada EPI é atribuído a no máximo uma pessoa, na região apropriada."""
    presentes = {p["id"]: set() for p in pessoas}
    ambiguos = {p["id"]: set() for p in pessoas}
    regioes = {
        "capacete": (-0.1, 0.3, 0.1),
        "oculos": (0.0, 0.4, 0.2),
        "mascara": (0.05, 0.5, 0.25),
        "colete": (0.2, 0.8, 0.5),
        "luvas": (0.2, 1.0, 0.6),
    }
    for deteccao in deteccoes:
        item = (identificar_ausencia if ausencia else identificar_epi)(deteccao["classe"])
        if item is None:
            continue
        confianca = deteccao.get("confianca", 1.0)
        if not math.isfinite(confianca) or not 0 <= confianca <= 1:
            continue
        if confianca < (0.15 if item == "oculos" else 0.5):
            continue
        ex1, ey1, ex2, ey2 = deteccao["caixa"]
        cx, cy = (ex1 + ex2) / 2, (ey1 + ey2) / 2
        candidatos = []
        minimo, maximo, ancora = regioes[item]
        for pessoa in pessoas:
            x1, y1, x2, y2 = pessoa["caixa"]
            px, py = (cx - x1) / max(x2 - x1, 1), (cy - y1) / max(y2 - y1, 1)
            if item == "oculos":
                referencia = referencia_olhos(pessoa["caixa"], pessoa.get("pontos", {}))
                if referencia is None:
                    continue
                olho_x, olho_y, distancia = referencia
                largura_item, altura_item = ex2 - ex1, ey2 - ey1
                if (
                    abs(cx - olho_x) <= distancia * 1.2
                    and abs(cy - olho_y) <= distancia * 0.8
                    and distancia * 0.7 <= largura_item <= distancia * 5
                    and distancia * 0.12 <= altura_item <= distancia * 2.5
                ):
                    candidatos.append((math.hypot(cx - olho_x, cy - olho_y) / distancia, pessoa["id"]))
            elif 0 <= px <= 1 and minimo <= py <= maximo:
                candidatos.append((math.hypot(px - 0.5, py - ancora), pessoa["id"]))
        candidatos.sort()
        if len(candidatos) > 1 and candidatos[1][0] - candidatos[0][0] < 0.12:
            for _, pessoa_id in candidatos:
                ambiguos[pessoa_id].add(item)
        elif candidatos and confianca >= 0.5:
            presentes[candidatos[0][1]].add(item)
        elif candidatos:
            # Evidência fraca de óculos bloqueia alerta; não comprova presença.
            ambiguos[candidatos[0][1]].add(item)
    return presentes, ambiguos


def classificar_postura(angulo, proporcao):
    """Inclinação em pixels relativa à vertical da imagem, não à gravidade."""
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (angulo, proporcao)):
        return None
    if not 0 <= angulo <= 90 or proporcao <= 0:
        return None
    if angulo >= 55 or (angulo >= 45 and proporcao >= 1.15):
        return "Deitada"
    if angulo <= 30 and proporcao <= 1.25:
        return "Em pe"
    return None  # Inclinação intermediária/caixa contraditória não significa em pé.


def regiao_pose(caixa, tamanho):
    """Margem para não cortar articulações na borda da detecção de pessoa."""
    x1, y1, x2, y2 = caixa
    mx, my = max(8, int((x2 - x1) * 0.15)), max(8, int((y2 - y1) * 0.15))
    return (max(0, x1 - mx), max(0, y1 - my),
            min(tamanho[1], x2 + mx), min(tamanho[0], y2 + my))


def mapear_pontos_pose(marcos, regiao, caixa):
    """Devolve pontos do recorte ampliado ao referencial da caixa da pessoa."""
    rx1, ry1, rx2, ry2 = regiao
    x1, y1, x2, y2 = caixa
    return {
        i: ((rx1 + p.x * (rx2 - rx1) - x1) / (x2 - x1),
            (ry1 + p.y * (ry2 - ry1) - y1) / (y2 - y1), p.visibility)
        for i, p in enumerate(marcos)
    }


def avaliar_postura(pontos, caixa):
    resultado = {"postura": None, "angulo": None, "motivo": "Ombros e quadris sem visibilidade suficiente."}
    if len(caixa) != 4 or not all(math.isfinite(v) for v in caixa):
        return resultado
    largura, altura = caixa[2] - caixa[0], caixa[3] - caixa[1]
    if largura <= 0 or altura <= 0:
        return resultado

    def pixel(indice):
        ponto = pontos.get(indice)
        if ponto is None or len(ponto) < 3:
            return None
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in ponto[:3]):
            return None
        x, y, visibilidade = ponto[:3]
        if visibilidade < 0.5 or not (-0.25 <= x <= 1.25 and -0.25 <= y <= 1.25):
            return None
        return x * largura, y * altura

    lados = []
    minimo = max(12, min(largura, altura) * 0.08)
    for ombro, quadril in ((11, 23), (12, 24)):
        o, q = pixel(ombro), pixel(quadril)
        if o is not None and q is not None:
            vetor = (q[0] - o[0], q[1] - o[1])
            if math.hypot(*vetor) >= minimo:
                lados.append(vetor)
    if not lados:
        return resultado
    if len(lados) == 2:
        a, b = lados
        cosseno = (a[0] * b[0] + a[1] * b[1]) / (math.hypot(*a) * math.hypot(*b))
        if cosseno < math.cos(math.radians(45)):
            resultado["motivo"] = "Os dois lados do tronco apresentam posições contraditórias."
            return resultado
    dx = sum(v[0] for v in lados) / len(lados)
    dy = sum(v[1] for v in lados) / len(lados)
    if math.hypot(dx, dy) < minimo:
        return resultado
    angulo = math.degrees(math.atan2(abs(dx), abs(dy)))
    postura = classificar_postura(angulo, largura / altura)
    # Um tronco inclinado com pernas verticais e caixa alta pode estar curvado,
    # e não deitado. Sem evidência adicional a leitura fica inconclusiva.
    if postura == "Deitada" and largura < altura:
        for quadril, tornozelo in ((23, 27), (24, 28)):
            q, t = pixel(quadril), pixel(tornozelo)
            if q is not None and t is not None and t[1] - q[1] > minimo:
                angulo_perna = math.degrees(math.atan2(abs(t[0] - q[0]), t[1] - q[1]))
                if angulo_perna <= 25:
                    postura = None
                    break
    resultado.update(postura=postura, angulo=round(angulo, 1), motivo=(
        "Inclinação intermediária ou posição ambígua do corpo." if postura is None
        else "Postura estimada pela inclinação do tronco visível."
    ))
    return resultado


def postura_por_pontos(pontos, caixa):
    return avaliar_postura(pontos, caixa)["postura"]


class MotorAlertas:
    def __init__(self, confirmacao_epi=3, confirmacao_queda=2, intervalo=60, chao_y=None):
        self.confirmacao_epi = confirmacao_epi
        self.confirmacao_queda = confirmacao_queda
        self.rastreador = RastreadorPessoas()
        self.confirmador = ConfirmadorAlertas(intervalo)
        self.processamento_anterior = 0
        self.temporais = {}
        self.chao_y = chao_y

    def avaliar(self, caixas, pontos, deteccoes_epi, obrigatorios, suportados, tamanho, agora,
                processamento_segundos=None):
        # Usa a duração medida da inferência, nunca um intervalo arbitrário sem imagens.
        # A duração de confirmação e a exigência de três observações são mantidas.
        tolerancia = 2.0
        if (isinstance(processamento_segundos, (int, float))
                and math.isfinite(processamento_segundos) and processamento_segundos >= 0):
            maior = max(processamento_segundos, self.processamento_anterior)
            tolerancia = min(10.0, max(2.0, maior * 2 + 0.5))
            self.processamento_anterior = processamento_segundos
        self.rastreador.tolerancia = self.confirmador.tolerancia = tolerancia
        ids = self.rastreador.atualizar(caixas, agora)
        self.confirmador.limpar_ausentes(set(ids), set(self.rastreador.pessoas))
        pessoas = [{"id": pessoa_id, "caixa": tuple(caixa), "pontos": landmarks}
                   for pessoa_id, caixa, landmarks in zip(ids, caixas, pontos)]
        presentes, ambiguos = associar_epis(pessoas, deteccoes_epi)
        ausentes, ausencia_ambigua = associar_epis(pessoas, deteccoes_epi, ausencia=True)
        for pessoa_id in set(self.temporais) - set(ids):
            self.temporais.pop(pessoa_id, None)  # Oclusão interrompe evidência temporal.
        alertas = []
        for pessoa, landmarks in zip(pessoas, pontos):
            pessoa.pop("pontos", None)
            pessoa_id = pessoa["id"]
            postura = avaliar_postura(landmarks, pessoa["caixa"])
            pessoa.update(postura=postura["postura"], postura_angulo=postura["angulo"],
                          postura_motivo=postura["motivo"])
            chave_queda = (pessoa_id, "queda", "")
            incerto = self.rastreador.pessoas[pessoa_id].ambiguo
            pessoa['rastreamento_confiavel'] = not incerto
            temporal = self.temporais.setdefault(pessoa_id, AnaliseTemporal(confirmacao=self.confirmacao_queda, chao_y=self.chao_y))
            if incerto:
                temporal.interromper()
            pessoa.update(temporal.avaliar({} if incerto else landmarks, pessoa['caixa'], postura, agora, tamanho[0]))
            pessoa['queda_confirmada'] = pessoa['emergencia']  # Compatibilidade da API do painel.
            pessoa["queda_confirmacao_segundos"] = self.confirmacao_queda
            if pessoa['novo_evento'] and self.confirmador.pode_alertar(chave_queda, agora):
                alertas.append({"tipo": "queda", "pessoa_id": pessoa_id, "chaves": [chave_queda],
                                'classificacao': pessoa['situacao'], 'confirmacao': 'verificacao_humana_pendente',
                                "motivo": f"Pessoa {pessoa_id}: {pessoa['situacao_rotulo']}. Verificar presencialmente; sem diagnóstico médico."})
            estados = {}
            chaves_epi = []
            for item in obrigatorios:
                estado = "inconclusivo"
                if item in suportados and not incerto and landmarks.get('_imagem_adequada', True):
                    conflito = item in presentes[pessoa_id] and item in ausentes[pessoa_id]
                    if item in presentes[pessoa_id] and not conflito:
                        estado = "presente"
                    elif (not conflito and item in ausentes[pessoa_id]
                          and item not in ambiguos[pessoa_id] and item not in ausencia_ambigua[pessoa_id]
                          and regiao_verificavel(
                        item, pessoa["caixa"], landmarks, tamanho
                    )):
                        estado = "observando"
                chave = (pessoa_id, "epi", item)
                confirmado = self.confirmador.observar(
                    chave, estado == "observando", agora, self.confirmacao_epi
                )
                if confirmado:
                    estado = "possivel_ausencia"
                    if self.confirmador.pode_alertar(chave, agora):
                        chaves_epi.append(chave)
                estados[item] = estado
            pessoa["epis"] = estados
            pessoa["epi_faltando"] = [item for item, estado in estados.items() if estado == "possivel_ausencia"]
            if chaves_epi:
                itens = ", ".join(chave[2] for chave in chaves_epi)
                alertas.append({"tipo": "epi", "pessoa_id": pessoa_id, "chaves": chaves_epi,
                                'confirmacao': 'verificacao_humana_pendente', 'epis': [c[2] for c in chaves_epi],
                                "motivo": f"Pessoa {pessoa_id}: possível ausência de {itens}, persistente por {self.confirmacao_epi:g} s."})
        return pessoas, alertas
