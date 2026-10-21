import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from PIL import Image

from dataset_ia import auditar_dataset, CLASSES_ORIGINAIS
from preparar_dataset import preparar
from avaliar_eventos import avaliar


class TestDataset(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.raiz = Path(self.temp.name)

    def config(self):
        dados = dict(names=CLASSES_ORIGINAIS)
        for i, s in enumerate(('train', 'val', 'test')):
            dados[s] = 'images/' + s
            imagens = self.raiz / 'images' / s
            labels = self.raiz / 'labels' / s
            imagens.mkdir(parents=True, exist_ok=True)
            labels.mkdir(parents=True, exist_ok=True)
            Image.new('RGB', (80, 80), (i * 50, 10, 100)).save(imagens / 'a.png')
            (labels / 'a.txt').write_text('0 .5 .5 .4 .4\n2 .5 .5 .2 .1\n')
        caminho = self.raiz / 'data.yaml'
        caminho.write_text(yaml.safe_dump(dados), encoding='utf-8')
        return caminho

    def test_faltam_imagens_e_teste_sem_inventar_contagens(self):
        p = self.raiz / 'data.yaml'
        p.write_text(yaml.safe_dump(dict(names=CLASSES_ORIGINAIS, train='images/train', val='images/val')))
        r = auditar_dataset(p)
        self.assertTrue(r['erros'])
        self.assertEqual(r['divisoes']['train']['imagens'], 0)

    def test_dataset_valido_sem_grupos_nao_comprova_independencia(self):
        r = auditar_dataset(self.config())
        self.assertFalse(r['erros'])
        self.assertFalse(r['grupos_verificados'])

    def test_pixels_duplicados_entre_divisoes_sao_erro(self):
        p = self.config()
        Image.open(self.raiz / 'images/train/a.png').save(self.raiz / 'images/test/a.png')
        self.assertTrue(any('duplicados' in e for e in auditar_dataset(p)['erros']))

    def test_labels_fora_da_imagem_e_classes_invalidas(self):
        p = self.config()
        for texto in ('9 .5 .5 .2 .2', '0 .98 .5 .4 .4', '0 nan .5 .4 .4', '0 .5 .5 0 .4'):
            with self.subTest(texto=texto):
                (self.raiz / 'labels/train/a.txt').write_text(texto)
                self.assertTrue(auditar_dataset(p)['erros'])

    def test_negativos_precisam_ser_revisados_e_ter_label_vazio(self):
        p = self.config()
        (self.raiz / 'labels/train/a.txt').write_text('')
        self.assertEqual(auditar_dataset(p)['divisoes']['train']['negativos'], 1)
        (self.raiz / 'labels/train/a.txt').unlink()
        self.assertTrue(auditar_dataset(p)['erros'])

    def manifesto(self):
        entradas = []
        for i in range(9):
            Image.new('RGB', (80, 80), (i * 20, 20, 10)).save(self.raiz / f'{i}.png')
            (self.raiz / f'{i}.txt').write_text('0 .5 .5 .5 .5')
            entradas.append(dict(imagem=f'{i}.png', label=f'{i}.txt', grupos=[f'pessoa:{i // 3}', f'seq:{i // 3}'],
                                 fonte='criação sintética de teste', licenca='teste local', autorizada=True, revisada=True))
        p = self.raiz / 'fonte.json'
        p.write_text(json.dumps(dict(classes=CLASSES_ORIGINAIS, imagens=entradas)), encoding='utf-8')
        return p

    def test_preparacao_preserva_pessoas_e_sequencias_e_nao_sobrescreve(self):
        p = self.manifesto()
        destino = self.raiz / 'preparado'
        r = preparar(p, destino)
        self.assertFalse(r['erros'])
        self.assertTrue(r['grupos_verificados'])
        self.assertEqual(sum(d['imagens'] for d in r['divisoes'].values()), 9)
        with self.assertRaises(ValueError):
            preparar(p, destino)

    def test_preparacao_recusa_fontes_sem_autorizacao(self):
        p = self.manifesto()
        d = json.loads(p.read_text())
        d['imagens'][0]['autorizada'] = False
        p.write_text(json.dumps(d))
        with self.assertRaises(ValueError):
            preparar(p, self.raiz / 'preparado')
        self.assertFalse((self.raiz / 'preparado').exists())

    def test_auditoria_detecta_pessoa_compartilhada_entre_splits(self):
        p = self.manifesto()
        destino = self.raiz / 'preparado'
        preparar(p, destino)
        m = destino / 'manifesto.json'
        registros = json.loads(m.read_text())
        for r in registros:
            r['grupos'] = ['pessoa:mesma']
        m.write_text(json.dumps(registros))
        self.assertTrue(any('Vazamento' in e for e in auditar_dataset(destino / 'data.yaml')['erros']))


class TestMetricasEventos(unittest.TestCase):
    def test_correspondencia_um_para_um_latencia_e_falsos(self):
        ref = dict(video_id='teste', duracao_segundos=3600,
                   eventos=[dict(inicio=10, fim=12, pessoa_id=1), dict(inicio=40, fim=42, pessoa_id=2)])
        pred = dict(video_id='teste', duracao_segundos=3600,
                    eventos=[dict(tempo=13, pessoa_id=1), dict(tempo=14, pessoa_id=1), dict(tempo=100, pessoa_id=2)])
        r = avaliar(ref, pred)
        self.assertEqual(r['recall_por_evento'], .5)
        self.assertEqual(r['perdidos'], 1)
        self.assertEqual(r['falsos_alertas_por_hora'], 2)
        self.assertEqual(r['latencias_segundos'], [3])

    def test_sem_eventos_recall_indisponivel(self):
        dados = dict(video_id='teste', duracao_segundos=60, eventos=[])
        self.assertIsNone(avaliar(dados, dados)['recall_por_evento'])

    def test_video_divergente_e_tempo_invalido_recusados(self):
        ref = dict(video_id='a', duracao_segundos=60, eventos=[])
        for pred in (dict(video_id='b', duracao_segundos=60, eventos=[]),
                     dict(video_id='a', duracao_segundos=60, eventos=[dict(tempo=70, pessoa_id=1)])):
            with self.assertRaises(ValueError):
                avaliar(ref, pred)


class TestRuntime(unittest.TestCase):
    def test_cpu_forcado_e_fallback_sem_cuda(self):
        from types import SimpleNamespace
        from runtime_ia import opcoes_inferencia
        for disponivel, pedido, esperado in ((True, 'cpu', 'cpu'), (False, 'auto', 'cpu'), (True, 'auto', 0)):
            with patch.dict('sys.modules', {'torch': SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: disponivel))}), patch.dict('os.environ', {'VIGIAAI_DEVICE': pedido}):
                self.assertEqual(opcoes_inferencia()['device'], esperado)


if __name__ == '__main__':
    unittest.main()
