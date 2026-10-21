import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from epi_monitoramento import MotorAlertas, avaliar_postura, identificar_epi, identificar_ausencia, RastreadorPessoas, ConfirmadorAlertas
from queda_temporal import AnaliseTemporal
from main import Monitor


EM_PE = (100, 50, 300, 450)
DEITADA = (140, 310, 500, 480)


def marcos(deitada=False):
    if deitada:
        return {0: (.2, .3, 1), 11: (.3, .4, 1), 12: (.3, .5, 1),
                23: (.75, .4, 1), 24: (.75, .5, 1)}
    return {0: (.5, .1, 1), 11: (.4, .25, 1), 12: (.6, .25, 1),
            23: (.4, .65, 1), 24: (.6, .65, 1), 2: (.4, .1, 1), 5: (.6, .1, 1)}


class TestTemporal(unittest.TestCase):
    def ler(self, temporal, t, deitada=False, caixa=None, pontos=None):
        caixa = caixa or (DEITADA if deitada else EM_PE)
        pontos = marcos(deitada) if pontos is None else pontos
        return temporal.avaliar(pontos, caixa, avaliar_postura(pontos, caixa), t, 720)

    def ereta(self, temporal):
        for t in (0, .25, .5):
            self.ler(temporal, t)

    def test_queda_exige_transicao_rapida_e_persistencia(self):
        a = AnaliseTemporal()
        self.ereta(a)
        for t in (.75, 1, 1.5, 2):
            r = self.ler(a, t, True)
            self.assertFalse(r['emergencia'])
        r = self.ler(a, 2.75, True)
        self.assertEqual(r['situacao'], 'queda_observada')
        self.assertTrue(r['novo_evento'])
        self.assertFalse(self.ler(a, 3, True)['novo_evento'])

    def test_colapso_e_hipotese_visual_sem_diagnostico(self):
        a = AnaliseTemporal()
        self.ereta(a)
        pontos = marcos(True)
        pontos[23], pontos[24] = (.5, .4, 1), (.5, .5, 1)
        for t in (.75, 1, 1.5, 2, 2.75):
            r = self.ler(a, t, True, caixa=(20, 310, 380, 480), pontos=pontos)
        self.assertEqual(r['situacao'], 'possivel_colapso')
        self.assertTrue(r['emergencia'])

    def test_encontrada_deitada_nao_vira_queda_observada(self):
        a = AnaliseTemporal()
        for t in range(6):
            r = self.ler(a, t, True)
        self.assertEqual(r['situacao'], 'encontrada_caida_imovel')
        self.assertTrue(r['emergencia'])
        self.assertFalse(r['chao_verificado'])

    def test_deitada_em_movimento_nao_e_imovel(self):
        a = AnaliseTemporal()
        for t in range(8):
            r = self.ler(a, t, True, caixa=(140 + t * 30, 310, 500 + t * 30, 480))
        self.assertFalse(r['emergencia'])

    def test_transicao_gradual_nao_inventa_acidente(self):
        a = AnaliseTemporal()
        self.ereta(a)
        # Tronco intermediário durante uma transição lenta, sem inferir intenção.
        pontos = {0: (.5, .1, 1), 11: (.3, .3, 1), 12: (.4, .3, 1),
                  23: (.55, .5, 1), 24: (.65, .5, 1)}
        for t in (.75, 1, 1.5, 2):
            self.ler(a, t, pontos=pontos)
        for t in (2.5, 3, 4, 5, 6, 7, 8):
            r = self.ler(a, t, True)
        self.assertFalse(r['emergencia'])
        self.assertTrue(a.transicao_lenta)

    def test_oclusao_e_baixo_fps_interrompem_evidencia(self):
        for falha in ('oclusao', 'pausa'):
            a = AnaliseTemporal()
            self.ereta(a)
            if falha == 'oclusao':
                self.ler(a, .6, pontos={})
                t = .75
            else:
                t = 4
            r = self.ler(a, t, True)
            self.assertEqual(r['situacao'], 'deitada_sem_queda_observada')
            self.assertFalse(r['emergencia'])

    def test_relogio_repetido_nao_acumula_observacoes(self):
        a = AnaliseTemporal()
        for _ in range(10):
            r = self.ler(a, 0, True)
        self.assertFalse(r['emergencia'])
        self.assertEqual(r['queda_quadros'], 1)

    def test_recuperacao_e_novo_episodio(self):
        a = AnaliseTemporal()
        self.ereta(a)
        for t in (.75, 1.5, 2, 2.75):
            self.ler(a, t, True)
        self.assertEqual(self.ler(a, 3)['situacao'], 'recuperando')
        for t in (3.25, 3.5, 3.75, 4):
            r = self.ler(a, t)
        self.assertFalse(a.emitiu)
        self.assertEqual(r['situacao'], 'em_pe')

    def test_cabeca_oculta_nao_prova_queda(self):
        a = AnaliseTemporal()
        self.ereta(a)
        pontos = marcos(True)
        pontos.pop(0)
        r = self.ler(a, .75, True, pontos=pontos)
        self.assertEqual(r['situacao'], 'deitada_sem_queda_observada')

    def test_agachar_com_pernas_verticais_nao_e_deitar(self):
        a = AnaliseTemporal()
        p = marcos()
        p.update({23: (.65, .4, 1), 24: (.85, .4, 1), 27: (.65, .95, 1), 28: (.85, .95, 1)})
        for t in range(7):
            r = self.ler(a, t, pontos=p)
        self.assertFalse(r['emergencia'])


class TestEPIConservador(unittest.TestCase):
    def test_mesma_ausencia_nao_repete_apos_cooldown(self):
        m = MotorAlertas()
        total = 0
        for t in range(75):
            _, eventos = m.avaliar([EM_PE], [marcos()], [{'classe': 'no_helmet', 'caixa': (150, 55, 250, 105)}],
                                  ['capacete'], {'capacete'}, (720, 1280, 3), t)
            for e in eventos:
                total += 1
                m.confirmador.marcar_alerta(e['chaves'], t)
        self.assertEqual(total, 1)

    def test_timestamps_iguais_nao_contam_como_quadros_distintos(self):
        c = ConfirmadorAlertas(tolerancia=5)
        chave = (1, 'epi', 'capacete')
        c.observar(chave, True, 0, 3)
        c.observar(chave, True, 3, 3)
        self.assertFalse(c.observar(chave, True, 3, 3))
        self.assertTrue(c.observar(chave, True, 4, 3))

    def avaliar(self, deteccoes, qualidade=True):
        m = MotorAlertas()
        pontos = marcos() | {'_imagem_adequada': qualidade}
        for t in (0, 1, 2, 3):
            p, a = m.avaliar([EM_PE], [pontos], deteccoes, ['capacete', 'oculos'], {'capacete', 'oculos'}, (720, 1280, 3), t)
        return p[0], a

    def test_ausencia_precisa_classe_explicita(self):
        p, a = self.avaliar([])
        self.assertFalse(a)
        self.assertEqual(set(p['epis'].values()), {'inconclusivo'})
        p, a = self.avaliar([{'classe': 'no_helmet', 'caixa': (150, 55, 250, 105), 'confianca': .9}])
        self.assertEqual(p['epis']['capacete'], 'possivel_ausencia')
        self.assertEqual(len(a), 1)

    def test_baixa_luz_e_conflito_nao_geram_ausencia(self):
        negativo = {'classe': 'no_helmet', 'caixa': (150, 55, 250, 105), 'confianca': .9}
        p, a = self.avaliar([negativo], qualidade=False)
        self.assertFalse(a)
        p, a = self.avaliar([negativo, negativo | {'classe': 'helmet'}])
        self.assertEqual(p['epis']['capacete'], 'inconclusivo')
        self.assertFalse(a)

    def test_oculos_genericos_nao_comprovam_protecao(self):
        self.assertIsNone(identificar_epi('glasses'))
        self.assertEqual(identificar_ausencia('no_goggle'), 'oculos')

    def test_ids_em_cruzamento_nao_compartilham_confirmacao(self):
        m = MotorAlertas()
        for t in (0, 1, 2, 3):
            p, a = m.avaliar([EM_PE, (110, 50, 310, 450)], [marcos(), marcos()], [],
                             ['capacete'], {'capacete'}, (720, 1280, 3), t)
        self.assertFalse(a)
        self.assertTrue(all(not x['rastreamento_confiavel'] for x in p))

    def test_predicao_de_movimento_mantem_id_sem_sobreposicao(self):
        r = RastreadorPessoas()
        for t, x in enumerate((0, 80, 160, 240)):
            self.assertEqual(r.atualizar([(x, 10, x + 100, 410)], t * .5), [1])


class TestAlertasPrivados(unittest.TestCase):
    def test_imagem_antiga_nao_vira_recente_apos_processamento_lento(self):
        with tempfile.TemporaryDirectory() as pasta:
            m = Monitor(base=pasta, modelo_epi=None, modelo_oculos=None)
            m.status['executando'] = True
            m.frame_capturado_em = 10
            q = np.zeros((20, 20, 3), dtype=np.uint8)
            with patch('main.time.monotonic', return_value=20):
                m._publicar_frame(q, q, [], 1)
                self.assertFalse(m.snapshot()['coleta_disponivel'])

    def test_jpeg_em_pasta_com_acentos(self):
        from main import salvar_jpeg
        with tempfile.TemporaryDirectory() as pasta:
            alvo = Path(pasta) / 'ocorrência.jpg'
            salvar_jpeg(alvo, np.zeros((20, 20, 3), dtype=np.uint8))
            self.assertTrue(alvo.read_bytes().startswith(b'\xff\xd8'))

    def test_imagem_desativada_preserva_registro_sem_smtp(self):
        with tempfile.TemporaryDirectory() as pasta, patch.dict(os.environ, {'SALVAR_IMAGEM_OCORRENCIA': '0', 'VIGIAAI_TESTE': '1'}):
            m = Monitor(base=pasta, modelo_epi=None, modelo_oculos=None)
            with patch('main.smtplib.SMTP_SSL') as smtp, patch('main.salvar_jpeg') as salvar:
                m.alerta(np.zeros((20, 20, 3), dtype=np.uint8),
                         dict(tipo='queda', pessoa_id=1, chaves=[(1, 'queda', '')], motivo='Teste'), 0)
                m.email(m.eventos[0], None)
                smtp.assert_not_called()
                salvar.assert_not_called()
            self.assertIsNone(m.eventos[0]['arquivo'])
            self.assertIn('instante', m.eventos[0])
            self.assertFalse((Path(pasta) / 'capturas').exists())

    def test_camera_indisponivel_e_liberada(self):
        from types import SimpleNamespace
        camera = unittest.mock.Mock()
        camera.isOpened.return_value = False
        with tempfile.TemporaryDirectory() as pasta:
            m = Monitor(base=pasta, modelo_epi=None, modelo_oculos=None)
            with patch('main.abrir_camera', return_value=camera), patch.dict('sys.modules', {'mediapipe': SimpleNamespace(), 'ultralytics': SimpleNamespace(YOLO=object)}), patch('runtime_ia.opcoes_inferencia', return_value={'device': 'cpu'}):
                m.executar()
            self.assertEqual(m.status['estado'], 'erro')
            camera.release.assert_called_once()


if __name__ == '__main__':
    unittest.main()
