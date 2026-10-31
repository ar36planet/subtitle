"""Offline regressions. All subtitle content and model responses are fictional."""
import ast
import contextlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import pysubs2
# Linux does not need Tk installed: no widgets are instantiated in these tests.
try:
    import tkinter
except ModuleNotFoundError:
    tk = NS(Tk=object, ttk=NS(), filedialog=NS(asksaveasfilename=lambda: None),
            scrolledtext=NS(), messagebox=NS(showinfo=lambda: None, showerror=lambda: None))
    sys.modules['tkinter'] = tk
import transcriber

ROOT = Path(__file__).resolve().parents[1]
SOURCE = next(''.join(c['source']) for c in json.loads(
    (ROOT / 'colab_transcribe.ipynb').read_text())['cells']
    if 'def parse_numbered(raw):' in ''.join(c.get('source', [])))


def notebook():
    # Execute definitions/constants only: no downloads, shell, Colab or model setup.
    tree = ast.parse(SOURCE)
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) or
             isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and
             t.id in {'BASE_PROMPT', 'ROMAJI_RULE', 'MAX_CTX'} for t in n.targets)]
    env = dict(re=re, os=__import__('os'), batch_lines=50,
               translate_mode='分批翻譯', tqdm=lambda xs, **kw: xs,
               SYSTEM_PROMPT='Translate.', glossary='', glossary_file='',
               japanese_romaji=True, video_context='', GLOSSARY=[])
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<notebook-definitions>', 'exec'), env)
    return env


class Var:
    def __init__(self, value=''): self.value = value
    def get(self): return self.value
    def set(self, value): self.value = value


def cues():
    return pysubs2.SSAFile.from_string(
        '1\n00:00:01,200 --> 00:00:02,500\n星舟出發\n穿過雲海\n\n'
        '2\n00:00:03,700 --> 00:00:05,900\n月橋到了\n', format_='srt')


def app(subs):
    return NS(_trans_rows=[(ev, Var()) for ev in subs],
              after=lambda delay, fn: fn(), trans_status=Var(),
              trans_btn=NS(configure=lambda **kw: None))


class LegacyTests(unittest.TestCase):
    def assert_timing(self, actual, expected):
        self.assertEqual([(e.start, e.end) for e in actual],
                         [(e.start, e.end) for e in expected])

    def export(self, gui):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'fiction.srt')
            with patch.object(transcriber.filedialog, 'asksaveasfilename', return_value=path), \
                 patch.object(transcriber.messagebox, 'showinfo'), \
                 patch.object(transcriber.messagebox, 'showerror', side_effect=AssertionError):
                transcriber.App._export_srt(gui)
            return pysubs2.load(path)

    def test_duplicate_model_numbers_never_overwrite(self):
        subs = cues(); gui = app(subs)
        fake = NS(chat=lambda **kw: {'message': {'content': '1: First\n1: Different\n2: Bridge'}})
        with patch.dict(sys.modules, ollama=fake):
            transcriber.App._do_translate_ollama(gui, 'fiction-model', 2)
        out = self.export(gui)
        self.assert_timing(out, subs)
        for src, dst in zip(subs, out):
            self.assertIn(src.plaintext, dst.plaintext)
            self.assertIn('[TRANSLATION_FAILED]', dst.text)
            self.assertNotIn('Different', dst.text)

    def test_export_preserves_success_empty_and_whitespace(self):
        subs = cues(); subs.append(pysubs2.SSAEvent(start=6100, end=7900, text='星燈亮了'))
        gui = app(subs)
        for (_, var), text in zip(gui._trans_rows, ['Cloudship departs.', '', ' \t\n ']): var.set(text)
        out = self.export(gui)
        self.assert_timing(out, subs)
        self.assertEqual(out[0].text, 'Cloudship departs.')
        for src, dst in zip(subs[1:], out[1:]):
            self.assertIn(src.plaintext, dst.plaintext)
            self.assertIn('[TRANSLATION_FAILED]', dst.text)

    def test_gui_ollama_success_maps_by_number(self):
        gui = app(cues()); calls = []
        def chat(**kw):
            calls.append(kw)
            return {'message': {'content': '2: Moonbridge is here.\n1: Cloudship departs.'}}
        with patch.dict(sys.modules, ollama=NS(chat=chat)):
            transcriber.App._do_translate_ollama(gui, 'fiction-model', 2)
        self.assertEqual([v.get() for _, v in gui._trans_rows], ['Cloudship departs.', 'Moonbridge is here.'])
        self.assertEqual(calls[0]['model'], 'fiction-model')
        self.assert_timing(self.export(gui), cues())

    def test_notebook_exhaustion_bounded_and_marks_original_multiline(self):
        env = notebook(); calls = []
        def chat(**kw):
            calls.append(kw)
            return {'message': {'content': '1: Wrong\n1: Also wrong'}}
        with patch.dict(sys.modules, ollama=NS(chat=chat)), contextlib.redirect_stdout(io.StringIO()):
            translated = env['make_llm_translator']('fiction-model')([e.plaintext for e in cues()])
        self.assertEqual(len(calls), 2)
        subs = cues()
        for ev, text in zip(subs, translated): ev.plaintext = text
        out = pysubs2.SSAFile.from_string(subs.to_string('srt'), format_='srt')
        self.assert_timing(out, cues())
        for src, dst in zip(cues(), out):
            self.assertEqual(dst.plaintext, src.plaintext + ' [TRANSLATION_FAILED]')

    def test_notebook_parser_characterization(self):
        parse = notebook()['parse_numbered']
        self.assertEqual(parse('1: A\n1: B'), {})
        self.assertEqual(parse('<think>1: hidden</think>\n2： Bridge\n1. Ship'), {1: 'Bridge', 0: 'Ship'})

    def test_notebook_retry_repairs_missing_number(self):
        env = notebook(); responses = iter(['2: Bridge', '1: Ship'])
        with patch.dict(sys.modules, ollama=NS(chat=lambda **kw: {'message': {'content': next(responses)}})), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(env['make_llm_translator']('fiction')(['星舟', '月橋']), ['Ship', 'Bridge'])

    def test_glossary_priority_unmatched_and_prompt_rules(self):
        env = notebook(); env['glossary'] = '月橋=Moonbridge;月=Moon;月橋→Silverbridge;不存在=Absent'
        pairs = env['load_glossary']()
        self.assertEqual(pairs, [('不存在', 'Absent'), ('月橋', 'Silverbridge'), ('月', 'Moon')])
        prompt = env['build_system_prompt'](pairs)
        self.assertIn('月橋 → Silverbridge', prompt)
        self.assertIn('never Chinese pinyin', prompt)
        self.assertIn('淺草 → Asakusa', prompt)
        # Romaji is a prompt rule for Japanese proper nouns, not a text converter.
        self.assertIn('Japanese proper nouns', prompt)
        env['japanese_romaji'] = False
        self.assertNotIn('Hepburn', env['build_system_prompt']([]))
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            env['check_glossary'](['月橋', '星舟'], ['Silverbridge', 'Ship'], pairs[:2])
        self.assertEqual(log.getvalue(), '')

    def test_helsinki_gui_normal_call_and_output(self):
        class Tokenizer:
            def __call__(self, texts, **kw):
                self_texts.extend(texts)
                return {'input_ids': [1, 2]}
            def decode(self, token, **kw): return {1: 'Ship', 2: 'Bridge'}[token]
        self_texts = []; gui = app(cues())
        gui._last_model_id = 'fiction'; gui._translator = (Tokenizer(), NS(generate=lambda **kw: kw['input_ids']))
        with patch.dict(sys.modules, transformers=NS(MarianMTModel=object, MarianTokenizer=object)):
            transcriber.App._do_translate_helsinki(gui, 'fiction', 2)
        self.assertEqual(self_texts, ['星舟出發\\N穿過雲海', '月橋到了'])
        self.assertEqual([v.get() for _, v in gui._trans_rows], ['Ship', 'Bridge'])

    def test_notebook_file_output_english_bilingual_and_failed_multiline(self):
        # Run the actual file-processing loop, excluding setup and download cells.
        tree = ast.parse(SOURCE)
        loop = next(n for n in tree.body if isinstance(n, ast.For) and
                    isinstance(n.target, ast.Tuple))
        for style in ('英文', '中英雙語'):
            for failed in (False, True):
                with self.subTest(style=style, failed=failed), tempfile.TemporaryDirectory() as tmp:
                    path = str(Path(tmp) / 'fiction.srt')
                    cues().save(path)
                    env = notebook()
                    env.update(pysubs2=pysubs2, srts=[path], translated_files=[],
                               translate_output_dir=tmp, subtitle_style=style,
                               translate=lambda texts: [t + ' [TRANSLATION_FAILED]' for t in texts]
                               if failed else ['Ship', 'Bridge'])
                    with contextlib.redirect_stdout(io.StringIO()):
                        exec(compile(ast.Module(body=[loop], type_ignores=[]), '<file-loop>', 'exec'), env)
                    self.assertEqual(len(env['translated_files']), 1)
                    out = pysubs2.load(env['translated_files'][0])
                    self.assert_timing(out, cues())
                    if failed:
                        self.assertEqual(out[0].plaintext, '星舟出發\n穿過雲海 [TRANSLATION_FAILED]')
                    elif style == '中英雙語':
                        self.assertEqual(out[0].plaintext, '星舟出發\n穿過雲海\nShip')
                    else:
                        self.assertEqual(out[0].plaintext, 'Ship')

    def test_notebook_helsinki_glossary_replacement_and_priority(self):
        env = notebook()
        env['GLOSSARY'] = [('月橋', 'Moonbridge'), ('月', 'Moon')]
        seen = []
        class Inputs(dict):
            def to(self, device): return self
        class Tokenizer:
            def __call__(self, texts, **kw):
                seen.extend(texts)
                return Inputs(input_ids=texts)
            def batch_decode(self, generated, **kw): return ['Bridge', 'Ship']
        class Model:
            def to(self, device): return self
            def generate(self, **kw): return kw['input_ids']
        fake = NS(MarianTokenizer=NS(from_pretrained=lambda model: Tokenizer()),
                  MarianMTModel=NS(from_pretrained=lambda model: Model()))
        torch = NS(cuda=NS(is_available=lambda: False), no_grad=contextlib.nullcontext)
        with patch.dict(sys.modules, transformers=fake, torch=torch), contextlib.redirect_stdout(io.StringIO()):
            result = env['make_helsinki_translator']('fiction')(['月橋到了', '星舟'])
        self.assertEqual(result, ['Bridge', 'Ship'])
        self.assertEqual(seen, [' Moonbridge 到了', '星舟'])

    def test_romaji_prompt_boundary_does_not_rewrite_source(self):
        env = notebook(); env['SYSTEM_PROMPT'] = env['build_system_prompt']([])
        texts = ['淺草的星燈店', '月橋在中國', '普通的橋與月亮']
        calls = []
        def chat(**kw):
            calls.append(kw)
            return {'message': {'content': '1: Asakusa star shop\n2: Moonbridge in China\n3: An ordinary bridge and moon'}}
        with patch.dict(sys.modules, ollama=NS(chat=chat)):
            out = env['make_llm_translator']('fiction')(texts)
        self.assertEqual(out, ['Asakusa star shop', 'Moonbridge in China', 'An ordinary bridge and moon'])
        self.assertEqual(calls[0]['messages'][1]['content'],
                         '1: 淺草的星燈店\n2: 月橋在中國\n3: 普通的橋與月亮')
        self.assertIn('Japanese proper nouns', calls[0]['messages'][0]['content'])

    def test_notebook_whole_file_exhaustion_is_bounded(self):
        env = notebook(); env['translate_mode'] = '整份一次翻'
        calls = []
        def chat(**kw):
            calls.append(kw)
            return {'message': {'content': ''}}
        with patch.dict(sys.modules, ollama=NS(chat=chat)), contextlib.redirect_stdout(io.StringIO()):
            out = env['make_llm_translator']('fiction')(['星舟', '月橋'])
        self.assertEqual(len(calls), 2)
        self.assertEqual(out, ['星舟 [TRANSLATION_FAILED]', '月橋 [TRANSLATION_FAILED]'])


if __name__ == '__main__': unittest.main()
