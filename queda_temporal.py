"""Sinais visuais temporais por ID. Não estima intenção nem faz diagnóstico."""

import math
from collections import deque


def caracteristicas(pontos, caixa, postura, agora):
    x1, y1, x2, y2 = caixa
    w, h = x2 - x1, y2 - y1

    def ponto(i):
        p = pontos.get(i)
        if (p is None or len(p) < 3 or not all(math.isfinite(v) for v in p[:3])
                or p[2] < 0.6 or not all(-0.25 <= v <= 1.25 for v in p[:2])):
            return None
        return x1 + p[0] * w, y1 + p[1] * h

    def meio(a, b):
        a, b = ponto(a), ponto(b)
        return tuple((u + v) / 2 for u, v in zip(a, b)) if a and b else a or b

    ombros, quadris = meio(11, 12), meio(23, 24)
    if postura['angulo'] is None or not ombros or not quadris:
        return None
    cabeca = ponto(0)  # Sem cabeça visível não infere uma transição de queda.
    return dict(t=agora, postura=postura['postura'], angulo=postura['angulo'],
                altura=h, centro=((x1 + x2) / 2, (y1 + y2) / 2),
                ombros=ombros, quadris=quadris, cabeca=cabeca,
                joelhos=meio(25, 26), tornozelos=meio(27, 28))


class AnaliseTemporal:
    def __init__(self, confirmacao=2, imobilidade=5, intervalo_maximo=1.25, chao_y=None):
        self.confirmacao = confirmacao
        self.imobilidade = imobilidade
        self.intervalo_maximo = intervalo_maximo
        self.chao_y = chao_y
        self.historico = deque(maxlen=180)
        self.evento = None
        self.deitada_desde = None
        self.imovel_desde = None
        self.quadros_deitada = 0
        self.transicao_lenta = False
        self.emitiu = False
        self.recuperando = False

    def interromper(self):
        self.historico.clear()
        self.evento = None
        self.deitada_desde = self.imovel_desde = None
        self.quadros_deitada = 0
        self.transicao_lenta = self.emitiu = self.recuperando = False

    def avaliar(self, pontos, caixa, postura, agora, altura_quadro):
        saida = dict(situacao='inconclusiva', situacao_rotulo='Situação inconclusiva',
                     situacao_motivo='Sem continuidade ou visibilidade suficiente.',
                     emergencia=False, novo_evento=False, queda_quadros=0,
                     queda_observada_segundos=0, velocidade_corpo=None,
                     imobilidade_segundos=0, chao_verificado=False)
        atual = caracteristicas(pontos, caixa, postura, agora)
        anterior = self.historico[-1] if self.historico else None
        if atual is None:
            self.interromper()
            return saida
        dt = agora - anterior['t'] if anterior else None
        if anterior and (dt <= 0 or dt > self.intervalo_maximo):
            self.interromper()
            anterior = None
        while self.historico and agora - self.historico[0]['t'] > 4:
            self.historico.popleft()
        escala = max([s['altura'] for s in self.historico] + [atual['altura'], 1])
        velocidade = None
        if anterior:
            velocidade = max(math.dist(atual[k], anterior[k]) for k in ('ombros', 'quadris')) / escala / dt
            saida['velocidade_corpo'] = round(velocidade, 3)
        deitada = atual['postura'] == 'Deitada'
        em_pe = atual['postura'] == 'Em pe'
        # Só há evidência de chão quando uma linha foi calibrada nesta câmera.
        perto_chao = (self.chao_y is not None and
                      atual['quadris'][1] >= self.chao_y * altura_quadro - escala * .2)
        saida['chao_verificado'] = perto_chao
        estaveis = [s for s in self.historico if s['postura'] == 'Em pe' and s['cabeca']]
        if deitada:
            if self.deitada_desde is None:
                self.deitada_desde = agora
            self.quadros_deitada += 1
            # Origem ereta sustentada; ao menos três observações anteriores.
            if not self.evento and len(estaveis) >= 3 and atual['cabeca']:
                base = estaveis[-1]
                duracao = agora - base['t']
                cabeca = (atual['cabeca'][1] - base['cabeca'][1]) / escala
                quadril = (atual['quadris'][1] - base['quadris'][1]) / escala
                if (duracao <= 1.25 and cabeca >= .18 and quadril >= .12
                        and cabeca / max(duracao, .001) >= .55 and atual['angulo'] - base['angulo'] >= 35):
                    deslocamento_x = abs(atual['quadris'][0] - base['quadris'][0]) / escala
                    tipo = 'possivel_colapso' if deslocamento_x < .1 else 'queda_observada'
                    self.evento = tipo
                elif duracao > 1.25:
                    self.transicao_lenta = True
            if velocidade is not None and velocidade <= .035:
                if self.imovel_desde is None:
                    self.imovel_desde = anterior['t']
            else:
                self.imovel_desde = None
            imovel = agora - self.imovel_desde if self.imovel_desde is not None else 0
            persistencia = agora - self.deitada_desde
            emergencia = bool(self.evento and persistencia >= self.confirmacao and self.quadros_deitada >= 3)
            tipo = self.evento or 'deitada_sem_queda_observada'
            if not self.evento and not self.transicao_lenta and imovel >= self.imobilidade and self.quadros_deitada >= 3:
                tipo, emergencia = 'encontrada_caida_imovel', True
            rotulos = {'queda_observada': 'Transição compatível com queda observada',
                       'possivel_colapso': 'Possível colapso visual; verificar pessoa',
                       'encontrada_caida_imovel': 'Pessoa encontrada deitada e imóvel',
                       'deitada_sem_queda_observada': 'Postura deitada sem queda observada'}
            motivo = ('Descida rápida de cabeça e quadris seguida de postura deitada.' if self.evento else
                      'Transição gradual; intenção de deitar não pode ser determinada.' if self.transicao_lenta else
                      'Não foi observada uma queda; imobilidade não confirma perda de consciência.')
            if not perto_chao:
                motivo += ' Proximidade do chão não confirmada.'
            saida.update(situacao=tipo, situacao_rotulo=rotulos[tipo], situacao_motivo=motivo,
                         emergencia=emergencia, novo_evento=emergencia and not self.emitiu,
                         queda_quadros=self.quadros_deitada,
                         queda_observada_segundos=round(persistencia, 2),
                         imobilidade_segundos=round(imovel, 2))
            if emergencia:
                self.emitiu = True  # Um aviso por episódio, até recuperação/interrupção.
        else:
            if self.evento or self.emitiu:
                self.recuperando = True
            self.deitada_desde = self.imovel_desde = None
            self.quadros_deitada = 0
            if em_pe:
                tipo = 'recuperando' if self.recuperando else 'em_pe'
                rotulo = 'Recuperando após ocorrência' if self.recuperando else 'Em pé'
                if not self.recuperando and velocidade is not None and velocidade > .12:
                    tipo, rotulo = 'em_movimento', 'Em movimento; possível caminhada'
                # Recuperação exige várias leituras eretas; não um único quadro.
                if self.recuperando and len(estaveis) >= 3 and all(s['postura'] == 'Em pe' for s in list(self.historico)[-3:]):
                    self.evento = None
                    self.emitiu = self.recuperando = self.transicao_lenta = False
            elif atual['joelhos'] and abs(atual['quadris'][1] - atual['joelhos'][1]) < escala * .18:
                tipo, rotulo = 'sentada_ou_agachada', 'Sentada ou agachada; situação ambígua'
            elif velocidade is not None and velocidade > .25 and atual['angulo'] >= 30:
                tipo, rotulo = 'possivel_desequilibrio', 'Possível perda de equilíbrio'
            else:
                tipo, rotulo = 'abaixando_ou_inclinada', 'Abaixando ou inclinada; sem queda confirmada'
            saida.update(situacao=tipo, situacao_rotulo=rotulo,
                         situacao_motivo='Estimativa visual temporal; requer verificação humana em caso de suspeita.')
        self.historico.append(atual)
        return saida
