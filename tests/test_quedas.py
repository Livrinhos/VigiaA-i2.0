import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from epi_monitoramento import (
    MotorAlertas, classificar_postura, mapear_pontos_pose, postura_por_pontos, regiao_pose,
)
from main import Monitor


def tronco(angulo, caixa=(100, 100, 500, 400), comprimento=120):
    """Marcos normalizados a partir de um mesmo tronco em pixels."""
    largura, altura = caixa[2] - caixa[0], caixa[3] - caixa[1]
    dx = math.sin(math.radians(angulo)) * comprimento / largura
    dy = math.cos(math.radians(angulo)) * comprimento / altura
    return {
        11: (0.25, 0.3, 0.95), 12: (0.35, 0.3, 0.95),
        23: (0.25 + dx, 0.3 + dy, 0.95),
        24: (0.35 + dx, 0.3 + dy, 0.95),
    }


class TestPosturaQuedas(unittest.TestCase):
    def test_deitada_inclinada_pela_perspectiva_nao_vira_em_pe(self):
        self.assertEqual(classificar_postura(50, 1.2), "Deitada")

    def test_faixa_ambigua_nao_e_em_pe(self):
        self.assertIsNone(classificar_postura(45, 0.7))

    def test_caixa_larga_sozinha_nao_prova_queda(self):
        self.assertIsNone(classificar_postura(0, 1.4))

    def test_valores_invalidos_nao_sao_em_pe(self):
        for angulo, proporcao in ((math.nan, 0.5), (math.inf, 0.5), (0, 0), (-1, 0.5)):
            with self.subTest(angulo=angulo, proporcao=proporcao):
                self.assertIsNone(classificar_postura(angulo, proporcao))

    def test_pontos_coincidentes_nao_sao_em_pe(self):
        pontos = {i: (0.5, 0.5, 1) for i in (11, 12, 23, 24)}
        self.assertIsNone(postura_por_pontos(pontos, (100, 100, 300, 500)))

    def test_coordenada_nan_nao_e_em_pe(self):
        pontos = {i: (math.nan, 0.5, 1) for i in (11, 12, 23, 24)}
        self.assertIsNone(postura_por_pontos(pontos, (100, 100, 300, 500)))

    def test_um_lado_visivel_permite_avaliar_pessoa_de_lado(self):
        caixa = (100, 100, 500, 400)
        pontos = tronco(80, caixa)
        pontos[12] = (*pontos[12][:2], 0.1)
        pontos[24] = (*pontos[24][:2], 0.1)
        self.assertEqual(postura_por_pontos(pontos, caixa), "Deitada")

    def test_lados_contraditorios_ficam_inconclusivos(self):
        pontos = {11: (0.2, 0.3, 1), 23: (0.2, 0.7, 1),
                  12: (0.4, 0.7, 1), 24: (0.4, 0.3, 1)}
        self.assertIsNone(postura_por_pontos(pontos, (100, 100, 300, 500)))

    def test_mesma_geometria_em_resolucoes_diferentes(self):
        for fator in (0.5, 1, 2):
            for angulo, postura in ((5, "Em pe"), (80, "Deitada")):
                caixa = tuple(v * fator for v in (100, 100, 300, 500))
                pontos = tronco(angulo, caixa, 100 * fator)
                self.assertEqual(postura_por_pontos(pontos, caixa), postura)

    def test_pernas_verticais_e_tronco_curvado_nao_confirmam_queda(self):
        caixa = (100, 100, 300, 500)
        pontos = tronco(70, caixa, 90)
        pontos[27] = (pontos[23][0], 0.95, 0.95)
        pontos[28] = (pontos[24][0], 0.95, 0.95)
        self.assertIsNone(postura_por_pontos(pontos, caixa))

    def test_pose_ausente_nao_confirma_queda_nem_em_pe(self):
        self.assertIsNone(postura_por_pontos({}, (100, 100, 500, 400)))

    def test_recorte_com_margem_preserva_referencial_original(self):
        caixa = (100, 100, 300, 500)
        regiao = regiao_pose(caixa, (720, 1280, 3))
        self.assertEqual(regiao, (70, 40, 330, 560))
        pontos = tronco(75, caixa, 90)
        marcos = [SimpleNamespace(x=0, y=0, visibility=0) for _ in range(33)]
        for i, (x, y, v) in pontos.items():
            marcos[i] = SimpleNamespace(
                x=(caixa[0] + x * 200 - regiao[0]) / (regiao[2] - regiao[0]),
                y=(caixa[1] + y * 400 - regiao[1]) / (regiao[3] - regiao[1]), visibility=v,
            )
        remapeados = mapear_pontos_pose(marcos, regiao, caixa)
        for i in pontos:
            self.assertAlmostEqual(remapeados[i][0], pontos[i][0])
            self.assertAlmostEqual(remapeados[i][1], pontos[i][1])
        self.assertEqual(postura_por_pontos(remapeados, caixa), "Deitada")

    def test_margem_nao_ultrapassa_a_imagem(self):
        self.assertEqual(regiao_pose((0, 0, 640, 480), (480, 640, 3)), (0, 0, 640, 480))


class TestQuedaComputadorLento(unittest.TestCase):
    caixa = (100, 100, 500, 400)

    def avaliar(self, motor, agora, processamento, caixas=None):
        caixas = [self.caixa] if caixas is None else caixas
        return motor.avaliar(
            caixas, [tronco(80, caixa) for caixa in caixas], [], [], set(),
            (720, 1280, 3), agora, processamento_segundos=processamento,
        )

    def test_quadros_lentos_mantem_id_sem_inventar_continuidade(self):
        motor = MotorAlertas()
        ids = []
        for agora in (0, 3, 6):
            pessoas, alertas = self.avaliar(motor, agora, 3)
            ids.append(pessoas[0]["id"])
        self.assertEqual(ids, [1, 1, 1])
        self.assertFalse(alertas)
        self.assertFalse(pessoas[0]['queda_confirmada'])

    def test_intervalo_grande_sem_processamento_lento_reinicia(self):
        motor = MotorAlertas()
        self.avaliar(motor, 0, 0.1)
        self.avaliar(motor, 1, 0.1)
        pessoas, alertas = self.avaliar(motor, 6, 0.1)
        self.assertFalse(alertas)
        self.assertFalse(pessoas[0]["queda_confirmada"])

    def test_pessoa_ausente_reinicia_mesmo_com_processamento_lento(self):
        motor = MotorAlertas()
        self.avaliar(motor, 0, 3)
        self.avaliar(motor, 3, 3)
        self.avaliar(motor, 4, 3, caixas=[])
        pessoas, alertas = self.avaliar(motor, 6, 3)
        self.assertFalse(alertas)
        self.assertFalse(pessoas[0]["queda_confirmada"])

    def test_pausa_superior_ao_limite_reinicia_ate_em_pc_lento(self):
        motor = MotorAlertas()
        self.avaliar(motor, 0, 8)
        self.avaliar(motor, 8, 8)
        pessoas, alertas = self.avaliar(motor, 30, 8)
        self.assertFalse(alertas)
        self.assertEqual(pessoas[0]["queda_quadros"], 1)


class TestIntegracaoQuedaLenta(unittest.TestCase):
    def test_pipeline_usa_instante_do_quadro_e_processamento_medido(self):
        relogio = [0.0]
        quadro = np.zeros((480, 640, 3), dtype=np.uint8)

        class Camera:
            leituras = 0
            liberada = False

            def isOpened(self):
                return True

            def read(self):
                self.leituras += 1
                if self.leituras <= 3:
                    return True, quadro.copy()
                monitor.stop.set()
                return False, None

            def release(self):
                self.liberada = True

        class Modelo:
            def __call__(self, *_args, **_kwargs):
                relogio[0] += 3
                return [SimpleNamespace(boxes=SimpleNamespace(xyxy=np.array([[100, 100, 500, 400]])))]

        class Pose:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def process(self, imagem):
                # O corpo recebe margem, não apenas a caixa apertada de YOLO.
                self_imagem = imagem.shape[:2]
                if self_imagem != (390, 520):
                    raise AssertionError(f"Recorte sem a margem esperada: {self_imagem}")
                marcos = [SimpleNamespace(x=0, y=0, visibility=0) for _ in range(33)]
                for i, ponto in tronco(80).items():
                    marcos[i] = SimpleNamespace(x=ponto[0], y=ponto[1], visibility=ponto[2])
                return SimpleNamespace(pose_landmarks=SimpleNamespace(landmark=marcos))

        with tempfile.TemporaryDirectory() as pasta:
            monitor = Monitor(base=Path(pasta), modelo_epi=None, modelo_oculos=None)
            monitor.status["executando"] = True
            camera = Camera()
            mp = SimpleNamespace(solutions=SimpleNamespace(pose=SimpleNamespace(Pose=lambda **_: Pose())))
            with patch('runtime_ia.opcoes_inferencia', return_value={'device': 'cpu', 'half': False, 'imgsz': 640}), patch("main.abrir_camera", return_value=camera), patch("main.time", SimpleNamespace(
                monotonic=lambda: relogio[0]
            )), patch.dict("sys.modules", {
                "mediapipe": mp, "ultralytics": SimpleNamespace(YOLO=lambda _: Modelo())
            }), patch.object(monitor, "alerta") as alerta, patch.object(
                monitor, "processar_deteccoes", wraps=monitor.processar_deteccoes
            ) as processar:
                monitor.executar()
            self.assertTrue(camera.liberada)
            self.assertEqual(monitor.status["estado"], "parado", monitor.status["mensagem"])
            self.assertEqual(monitor.status["deteccoes"][0]["postura"], "Deitada")
            self.assertEqual(monitor.status["deteccoes"][0]["id"], 1)
            self.assertFalse(monitor.status["deteccoes"][0]["queda_confirmada"])
            self.assertEqual(alerta.call_count, 0)
            self.assertEqual(processar.call_args.args[4], 6)
            self.assertEqual(processar.call_args.kwargs["processamento_segundos"], 3)


if __name__ == "__main__":
    unittest.main()
