"""Offline characterization of base code; all dialogue and names are fictional."""
import ast
from contextlib import nullcontext, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pysubs2

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/legacy_translation_regressions/imaginary.srt'
SOURCE = ['月燈車站到了 請帶上紙星星', '霧羽屋今天開門', '下一站是雲糖島']
ENGLISH = ['Moonlamp Station: bring paper stars.', 'Mistwing House is open.',
           'Next stop is Cloudcandy Island.']
TIMES = [(1125, 3450), (5010, 6999), (9500, 12000)]


def notebook():
    cells = json.loads((ROOT / 'colab_transcribe.ipynb').read_text())['cells']
    source = next(''.join(c['source']) for c in cells
                  if 'def load_glossary()' in ''.join(c['source']))
    before, main = source.split('# ── 主流程', 1)
    tree = ast.parse(before)
    # Execute actual definitions/constants, never Colab imports or installation cells.
    tree.body = [n for n in tree.body if isinstance(n, (ast.Assign, ast.FunctionDef))]
    ns = dict(re=re, os=os, pysubs2=pysubs2, tqdm=lambda x, **kw: x)
    exec(compile(tree, 'colab_transcribe.ipynb:translation', 'exec'), ns)
    ns.update(GLOSSARY=[], SYSTEM_PROMPT=ns['BASE_PROMPT'])
    return ns, main[main.index('\n'):]


def fake_helsinki(failure=None, cuda=False):
    class Inputs(dict):
        def to(self, device):
            return self
    inputs = Inputs(input_ids='fictional-tokens')
    tokenizer = Mock(return_value=inputs)
    tokenizer.batch_decode.side_effect = lambda out, **kw: out
    tokenizer.decode.side_effect = lambda out, **kw: out
    model = Mock()
    model.to.return_value = model
    model.generate.side_effect = failure
    model.generate.return_value = ENGLISH
    transformers = SimpleNamespace(
        MarianTokenizer=SimpleNamespace(from_pretrained=Mock(return_value=tokenizer)),
        MarianMTModel=SimpleNamespace(from_pretrained=Mock(return_value=model)))
    torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: cuda),
                            no_grad=nullcontext)
    return transformers, torch, tokenizer, model


class NotebookRegressions(unittest.TestCase):
    def setUp(self):
        self.ns, self.main = notebook()

    def test_glossary_separators_longest_first_and_file_override(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'terms.txt'
            path.write_text('\ufeff月燈=Moonlamp\n月燈車站=Moonlamp Station\n', encoding='utf-8')
            self.ns.update(glossary='月燈=Old;霧羽屋＝Mistwing House，雲糖島→Cloudcandy Island\n壞項=;忽略',
                           glossary_file=str(path))
            self.assertEqual(self.ns['load_glossary'](), [
                ('月燈車站', 'Moonlamp Station'), ('霧羽屋', 'Mistwing House'),
                ('雲糖島', 'Cloudcandy Island'), ('月燈', 'Moonlamp')])

    def test_missing_glossary_file_and_unmatched_terms(self):
        self.ns.update(glossary='月燈=Moonlamp', glossary_file='/nonexistent/fictional-terms.txt')
        with redirect_stdout(io.StringIO()) as output:
            pairs = self.ns['load_glossary']()
            self.ns['check_glossary'](['沒有匹配詞', '月燈'], ['A paper star.', 'MOONLAMP'], pairs)
        self.assertIn('找不到對照表', output.getvalue())
        self.assertNotIn('應為', output.getvalue())
        with redirect_stdout(io.StringIO()) as output:
            self.ns['check_glossary'](['月燈'], ['Wrong name'], pairs)
        self.assertIn('第 1 句: 月燈 應為 Moonlamp', output.getvalue())

    def test_romaji_rule_scope_toggle_context_and_explicit_terms(self):
        prompt = self.ns['build_system_prompt']([('月燈', 'Tsukiakari')])
        for expected in ['Hepburn', 'never Chinese pinyin', 'places, stations, temples',
                         '淺草 → Asakusa', '清水寺 → Kiyomizu-dera', '拉麵 → ramen',
                         'shops, brands, dishes', 'Background of the video:',
                         'Always translate these terms exactly as given:\n月燈 → Tsukiakari']:
            self.assertIn(expected, prompt)
        self.ns.update(japanese_romaji=False, video_context='   ')
        self.assertEqual(self.ns['build_system_prompt']([]), self.ns['BASE_PROMPT'])
        # No automatic conversion of arbitrary Chinese words or non-Japanese names.
        self.assertEqual(self.ns['parse_numbered']('1: 月燈\n2: Paper Star'),
                         {0: '月燈', 1: 'Paper Star'})

    def test_ollama_whole_and_batches_preserve_global_numbers(self):
        for mode, size, responses in [
            ('整份一次翻', 1, ['1: A\n2：B\n3. C']),
            ('分批翻', 2, ['1: A\n2: B', '3: C'])]:
            with self.subTest(mode=mode):
                chat = Mock(side_effect=[{'message': {'content': r}} for r in responses])
                self.ns.update(translate_mode=mode, batch_lines=size)
                with patch.dict(sys.modules, ollama=SimpleNamespace(chat=chat)):
                    actual = self.ns['make_llm_translator']('fictional-model')(SOURCE)
                self.assertEqual(actual, ['A', 'B', 'C'])
                call = chat.call_args_list[0].kwargs
                self.assertEqual(call['model'], 'fictional-model')
                self.assertEqual(call['options'], {'temperature': 0.2, 'num_ctx': 8192})
                self.assertEqual(call['messages'][0]['content'], self.ns['SYSTEM_PROMPT'])
                self.assertIn('1: ' + SOURCE[0], call['messages'][1]['content'])
                if mode == '分批翻':
                    self.assertEqual(chat.call_args_list[1].kwargs['messages'][1]['content'], '3: ' + SOURCE[2])

    def test_ollama_missing_retry_fallback_and_transport_error(self):
        chat = Mock(side_effect=[{'message': {'content': '<think>private reasoning</think>\n1: A\n99: ignore'}},
                                 {'message': {'content': '2: B'}}])
        with patch.dict(sys.modules, ollama=SimpleNamespace(chat=chat)), redirect_stdout(io.StringIO()) as output:
            actual = self.ns['make_llm_translator']('fake')(SOURCE)
        self.assertEqual(actual, ['A', 'B', SOURCE[2]])
        self.assertEqual(chat.call_count, 2)
        self.assertIn('保留原文', output.getvalue())
        chat.side_effect = RuntimeError('fictional offline failure')
        with patch.dict(sys.modules, ollama=SimpleNamespace(chat=chat)):
            with self.assertRaisesRegex(RuntimeError, 'fictional offline failure'):
                self.ns['make_llm_translator']('fake')(SOURCE)

    def test_helsinki_glossary_replacement_and_cpu_cuda(self):
        for cuda in (False, True):
            with self.subTest(cuda=cuda):
                transformers, torch, tokenizer, model = fake_helsinki(cuda=cuda)
                self.ns['GLOSSARY'] = [('月燈車站', 'Moonlamp Station'), ('月燈', 'Moonlamp')]
                original = SOURCE.copy()
                with patch.dict(sys.modules, transformers=transformers, torch=torch):
                    result = self.ns['make_helsinki_translator']('fictional-helsinki')(original)
                self.assertEqual(result, ENGLISH)
                self.assertEqual(original, SOURCE)
                tokenizer.assert_called_once_with(
                    [' Moonlamp Station 到了 請帶上紙星星', SOURCE[1], SOURCE[2]],
                    return_tensors='pt', padding=True, truncation=True, max_length=512)
                model.to.assert_called_once_with('cuda' if cuda else 'cpu')
                transformers.MarianTokenizer.from_pretrained.assert_called_once_with('fictional-helsinki')

    def test_helsinki_batches_and_failure_propagation(self):
        transformers, torch, tokenizer, model = fake_helsinki()
        model.generate.side_effect = [['A'] * 16, ['B']]
        with patch.dict(sys.modules, transformers=transformers, torch=torch):
            self.assertEqual(self.ns['make_helsinki_translator']('fake')(['虛構'] * 17), ['A'] * 16 + ['B'])
        self.assertEqual([len(c.args[0]) for c in tokenizer.call_args_list], [16, 1])
        model.generate.side_effect = RuntimeError('fictional generation failure')
        with patch.dict(sys.modules, transformers=transformers, torch=torch):
            with self.assertRaisesRegex(RuntimeError, 'fictional generation failure'):
                self.ns['make_helsinki_translator']('fake')(SOURCE)
        transformers.MarianTokenizer.from_pretrained.side_effect = RuntimeError('fictional load failure')
        with patch.dict(sys.modules, transformers=transformers, torch=torch):
            with self.assertRaisesRegex(RuntimeError, 'fictional load failure'):
                self.ns['make_helsinki_translator']('fake')

    def test_actual_notebook_srt_main_english_and_bilingual(self):
        for style, suffix in [('英文', 'en'), ('中英雙語', 'zh-en')]:
            with self.subTest(style=style), tempfile.TemporaryDirectory() as d:
                ns, main = notebook()
                translate = Mock(return_value=ENGLISH)
                ns.update(translate_output_dir=d, srt_source=str(FIXTURE),
                          collect_srts=lambda _: [str(FIXTURE)], free_whisper=lambda: None,
                          start_ollama=Mock(), make_llm_translator=lambda _: translate,
                          subtitle_style=style, translate_auto_download=False)
                with redirect_stdout(io.StringIO()):
                    exec(compile(main, 'colab_transcribe.ipynb:main', 'exec'), ns)
                translate.assert_called_once_with(SOURCE)
                result = pysubs2.load(str(Path(d) / f'imaginary.{suffix}.srt'))
                self.assertEqual([(e.start, e.end) for e in result], TIMES)
                originals = ['月燈車站到了\n請帶上紙星星', SOURCE[1], SOURCE[2]]
                expected = ENGLISH if style == '英文' else [f'{s}\n{e}' for s, e in zip(originals, ENGLISH)]
                self.assertEqual([e.plaintext for e in result], expected)

    def test_known_defect_duplicate_number_silently_overwrites(self):
        # Characterization only: this is NOT evidence of correct alignment.
        self.assertEqual(self.ns['parse_numbered']('1: First\n1: Overwritten'),
                         {0: 'Overwritten'})

    def test_notebook_main_reports_failure_without_output(self):
        with tempfile.TemporaryDirectory() as d:
            self.ns.update(translate_output_dir=d, srt_source=str(FIXTURE),
                           collect_srts=lambda _: [str(FIXTURE)], free_whisper=lambda: None,
                           start_ollama=lambda _: None,
                           make_llm_translator=lambda _: Mock(side_effect=RuntimeError('fictional failure')),
                           translate_auto_download=False)
            with redirect_stdout(io.StringIO()) as output:
                exec(compile(self.main, 'colab_transcribe.ipynb:main', 'exec'), self.ns)
            self.assertIn('RuntimeError: fictional failure', output.getvalue())
            self.assertEqual(list(Path(d).iterdir()), [])


class GuiRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('legacy_transcriber', ROOT / 'transcriber.py')
        cls.module = importlib.util.module_from_spec(spec)
        # No Tk installation/display is needed to exercise the actual App methods.
        widgets = {name: SimpleNamespace() for name in
                   ('ttk', 'filedialog', 'scrolledtext', 'messagebox')}
        tk = SimpleNamespace(Tk=object, **widgets)
        widgets['filedialog'].askopenfilename = Mock()
        widgets['filedialog'].asksaveasfilename = Mock()
        widgets['messagebox'].showerror = Mock()
        widgets['messagebox'].showinfo = Mock()
        with patch.dict(sys.modules, {'tkinter': tk}):
            spec.loader.exec_module(cls.module)

    def setUp(self):
        self.rows = [(e, Mock()) for e in pysubs2.load(str(FIXTURE))]
        self.app = SimpleNamespace(_trans_rows=self.rows, _translator=None, _last_model_id='',
                                   after=lambda delay, callback: callback(),
                                   trans_status=Mock(), trans_btn=Mock())

    def test_gui_ollama_call_and_output(self):
        chat = Mock(return_value={'message': {'content': '\n'.join(f'{i}: {t}' for i, t in enumerate(ENGLISH, 1))}})
        with patch.dict(sys.modules, ollama=SimpleNamespace(chat=chat)):
            self.module.App._do_translate_ollama(self.app, 'fictional-model', 3)
        self.assertEqual(chat.call_args.kwargs['model'], 'fictional-model')
        self.assertEqual(chat.call_args.kwargs['messages'][1]['content'],
                         '1: 月燈車站到了\\N請帶上紙星星\n2: 霧羽屋今天開門\n3: 下一站是雲糖島')
        for (_, var), text in zip(self.rows, ENGLISH):
            var.set.assert_called_once_with(text)
        self.app.trans_btn.configure.assert_called_with(state='normal', text='翻譯全部')

    def test_gui_ollama_and_helsinki_errors_restore_button(self):
        for backend in ('ollama', 'helsinki-load', 'helsinki-generate'):
            with self.subTest(backend=backend):
                transformers, _, _, model = fake_helsinki()
                if backend == 'helsinki-load':
                    transformers.MarianTokenizer.from_pretrained.side_effect = RuntimeError('fictional failure')
                model.generate.side_effect = RuntimeError('fictional failure')
                modules = dict(ollama=SimpleNamespace(chat=Mock(side_effect=RuntimeError('fictional failure'))),
                               transformers=transformers)
                with patch.dict(sys.modules, **modules), patch.object(self.module.messagebox, 'showerror') as error:
                    method = (self.module.App._do_translate_ollama if backend == 'ollama'
                              else self.module.App._do_translate_helsinki)
                    method(self.app, 'fake', 3)
                self.assertIn('fictional failure', error.call_args.args[1])
                self.app.trans_btn.configure.assert_called_with(state='normal', text='翻譯全部')
                for _, var in self.rows:
                    var.set.assert_not_called()

    def test_gui_helsinki_cache_and_output(self):
        transformers, _, tokenizer, model = fake_helsinki()
        with patch.dict(sys.modules, transformers=transformers):
            for _ in range(2):
                self.module.App._do_translate_helsinki(self.app, 'fictional-helsinki', 3)
        transformers.MarianMTModel.from_pretrained.assert_called_once_with('fictional-helsinki')
        self.assertEqual(model.generate.call_count, 2)
        for (_, var), text in zip(self.rows, ENGLISH):
            var.set.assert_called_with(text)
        tokenizer.assert_called_with([e.text.strip() for e, _ in self.rows],
                                     return_tensors='pt', padding=True, truncation=True, max_length=512)

    def test_known_defect_gui_export_omits_untranslated_rows(self):
        with tempfile.TemporaryDirectory() as d:
            output = str(Path(d) / 'partial.srt')
            for (_, var), text in zip(self.rows, [ENGLISH[0], '', ENGLISH[2]]):
                var.get.return_value = text
            with patch.object(self.module.filedialog, 'asksaveasfilename', return_value=output), patch.object(self.module.messagebox, 'showinfo'):
                self.module.App._export_srt(self.app)
            result = pysubs2.load(output)
            # Explicit reproduction of a base defect, not the desired goal behavior.
            self.assertEqual([e.plaintext for e in result], [ENGLISH[0], ENGLISH[2]])
            self.assertEqual([(e.start, e.end) for e in result], [TIMES[0], TIMES[2]])

    def test_gui_import_and_export_srt(self):
        with tempfile.TemporaryDirectory() as d:
            output = str(Path(d) / 'english.srt')
            self.app._populate_table = Mock()
            with patch.object(self.module.filedialog, 'askopenfilename', return_value=str(FIXTURE)):
                self.module.App._import_srt(self.app)
            self.assertEqual([(e.start, e.end) for e in self.app._srt_data], TIMES)
            self.assertEqual(self.app._srt_data[0].plaintext, '月燈車站到了\n請帶上紙星星')
            self.app._populate_table.assert_called_once_with(self.app._srt_data)
            for (_, var), text in zip(self.rows, ENGLISH):
                var.get.return_value = text
            with patch.object(self.module.filedialog, 'asksaveasfilename', return_value=output), patch.object(self.module.messagebox, 'showinfo'):
                self.module.App._export_srt(self.app)
            result = pysubs2.load(output)
            self.assertEqual([(e.start, e.end) for e in result], TIMES)
            self.assertEqual([e.plaintext for e in result], ENGLISH)


if __name__ == '__main__':
    unittest.main()
