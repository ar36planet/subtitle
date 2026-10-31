import ast
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from subtitle_cloud_backend import GeminiBackend, read_keychain, transport, _NoRedirect

# Entirely invented subtitles; credential sentinel is generated, never persisted.
REQUEST = {'cues': [{'id': 'moon-a', 'source': '月亮郵差\n到了'},
                    {'id': 'kite-b', 'source': '紙鳶開門'}],
           'source_language': 'zh', 'target_language': 'en'}
ROWS = [{'id': 'kite-b', 'text': 'The kite opens the door.'},
        {'id': 'moon-a', 'text': 'The lunar courier\nhas arrived.'}]


def response(rows=ROWS, *, text=None, finish='STOP'):
    return (200, {}, json.dumps({'candidates': [{'finishReason': finish,
        'content': {'parts': [{'text': text if text is not None else json.dumps({'items': rows})}]}}]}))


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.key = 'fake-' + 'sentinel-' + 'credential'
        self.env = patch.dict(os.environ, {'GEMINI_API_KEY': self.key})
        self.env.start()
        self.addCleanup(self.env.stop)

    def run_backend(self, responses, **kwargs):
        fake = Mock(side_effect=responses)
        backend = GeminiBackend(transport=fake, **kwargs)
        return backend(REQUEST), fake

    def assert_partition(self, result):
        ids = [r['id'] for r in result['items'] + result['failures']]
        self.assertCountEqual(ids, ['moon-a', 'kite-b'])
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotIn(self.key, json.dumps(result))

    def test_success_environment_priority_and_payload(self):
        reader = Mock(side_effect=AssertionError('must not read'))
        result, fake = self.run_backend([response()], keychain_reader=reader)
        self.assert_partition(result)
        self.assertEqual(result['items'][0], ROWS[1])
        reader.assert_not_called()
        url, headers, payload, timeout = fake.call_args.args
        self.assertNotIn(self.key, url)
        self.assertEqual(headers['x-goog-api-key'], self.key)
        self.assertEqual(timeout, 30)
        self.assertEqual(json.loads(payload['contents'][0]['parts'][0]['text']), REQUEST)

    def test_bad_model_outputs(self):
        cases = [('', 2), ('{"items":[', 2), ('explanation '+json.dumps({'items': ROWS}), 2),
                 ('<think>hmm</think>'+json.dumps({'items': ROWS}), 2),
                 (json.dumps({'items': [{'id': '1', 'text': 'renumbered'}]}), 2),
                 (json.dumps({'items': [ROWS[0]]}), 1),
                 (json.dumps({'items': [ROWS[0], ROWS[0], ROWS[1]]}), 1),
                 (json.dumps({'items': [ROWS[0], {'id': 'moon-a', 'text': ''}]}), 1),
                 ('{"items": [], "items": []}', 2),
                 (json.dumps({'items': [dict(ROWS[0], extra='split')]}), 2),
                 (json.dumps({'items': ROWS + [{'id': 'unknown', 'text': 'extra'}]}), 2),
                 (json.dumps({'items': [dict(ROWS[0], text=None), ROWS[1]]}), 1),
                 (json.dumps({'items': [{'id': 'moon-a+kite-b', 'text': 'merged'}]}), 2)]
        for raw, count in cases:
            with self.subTest(raw=raw):
                result, _ = self.run_backend([response(text=raw)])
                self.assert_partition(result)
                self.assertEqual(len(result['failures']), count)
                self.assertTrue(all(r['code'] == 'invalid_response' for r in result['failures']))
        result, _ = self.run_backend([response(finish='MAX_TOKENS')])
        self.assertEqual(len(result['failures']), 2)

    def test_missing_and_keychain(self):
        with patch.dict(os.environ, {}, clear=True):
            for reader in (Mock(return_value=None), Mock(side_effect=OSError('unavailable'))):
                result, fake = self.run_backend([], keychain_reader=reader)
                self.assertEqual(result['failures'][0]['code'], 'missing_key')
                self.assertIn('GEMINI_API_KEY', result['diagnostics'][0])
                fake.assert_not_called()
            reader = Mock(return_value=self.key)
            result, _ = self.run_backend([response()], keychain_reader=reader)
            self.assertFalse(result['failures'])
            reader.assert_called_once_with('subtitle-gemini', 'GEMINI_API_KEY')
        with patch('subtitle_cloud_backend.sys.platform', 'linux'), patch('subtitle_cloud_backend.subprocess.run') as run:
            self.assertIsNone(read_keychain('service', 'account'))
            run.assert_not_called()
        with patch('subtitle_cloud_backend.sys.platform', 'darwin'), patch('subtitle_cloud_backend.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=self.key+'\n')) as run:
            self.assertEqual(read_keychain('service', 'account'), self.key)
            self.assertEqual(run.call_args.kwargs['timeout'], 5)

    def test_retry_hints_and_fallback(self):
        detail = json.dumps({'error': {'details': [{'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '7.5s'}]}})
        for headers, body, expected in [({'Retry-After': '3'}, '{}', 3),
                ({'retry-after': 'Thu, 01 Jan 1970 00:01:50 GMT'}, '{}', 10),
                ({'Retry-After': '3'}, detail, 7.5),
                ({'Retry-After': '90'}, detail, 90),
                ({'Retry-After': 'nan'}, '{}', 1),
                ({'Retry-After': '-2'}, '{}', 1), ({}, 'bad', 1)]:
            with self.subTest(headers=headers):
                sleep = Mock()
                result, fake = self.run_backend([(429, headers, body), response()], sleep=sleep, clock=lambda: 100)
                self.assertFalse(result['failures'])
                sleep.assert_called_once_with(expected)
                self.assertEqual(fake.call_count, 2)
        sleep = Mock()
        result, fake = self.run_backend([(429, {}, '{}')]*5, sleep=sleep, max_retries=4, backoff_cap=3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [1, 2, 3, 3])
        self.assertEqual(fake.call_count, 5)
        self.assert_partition(result)
        self.assertTrue(all(f['code'] == 'retry_exhausted' for f in result['failures']))

    def test_no_secret_outputs_or_logs(self):
        cases = [(500, {}, self.key), RuntimeError(self.key),
                 response(text=self.key), response(rows=[dict(r, text=self.key) for r in ROWS]),
                 (200, {}, self.key), (401, {'secret': self.key}, self.key)]
        capture = io.StringIO()
        with contextlib.redirect_stdout(capture), contextlib.redirect_stderr(capture):
            for case in cases:
                result, _ = self.run_backend([case])
                self.assert_partition(result)
                self.assertTrue(result['failures'])
        self.assertNotIn(self.key, capture.getvalue())

    def test_http_adapter_without_network(self):
        from urllib.error import HTTPError
        opener = Mock()
        remote = Mock()
        remote.__enter__ = Mock(return_value=remote)
        remote.__exit__ = Mock(return_value=False)
        remote.status, remote.headers = 200, {'Content-Type': 'application/json'}
        remote.read.return_value = b'{}'
        opener.open.return_value = remote
        with patch('subtitle_cloud_backend.http.build_opener', return_value=opener):
            self.assertEqual(transport('https://example.invalid', {'x-goog-api-key': self.key}, {}, 8),
                             (200, remote.headers, b'{}'))
            self.assertEqual(opener.open.call_args.kwargs['timeout'], 8)
            opener.open.side_effect = HTTPError('https://example.invalid', 429, self.key,
                                               {'Retry-After': '2'}, io.BytesIO(b'{}'))
            self.assertEqual(transport('https://example.invalid', {}, {}, 8),
                             (429, {'Retry-After': '2'}, b'{}'))
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.invalid'))

    def test_configuration_bounds(self):
        for kwargs in ({'timeout': 0}, {'timeout': float('inf')}, {'max_retries': 11}, {'max_retries': -1}, {'model': '../bad'}):
            with self.assertRaises(ValueError):
                GeminiBackend(**kwargs)

    def test_existing_srt_import_export(self):
        # Execute existing methods without constructing Tk or requiring a display.
        import pysubs2
        tree = ast.parse(Path('transcriber.py').read_text())
        app = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'App')
        methods = [n for n in app.body if isinstance(n, ast.FunctionDef) and n.name in ('_import_srt', '_export_srt')]
        namespace = {'os': os, 'filedialog': Mock(), 'messagebox': Mock()}
        exec(compile(ast.Module(body=methods, type_ignores=[]), 'transcriber.py', 'exec'), namespace)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'input.srt'
            output = Path(directory)/'output.srt'
            source.write_text('1\n00:00:01,250 --> 00:00:02,750\n月亮郵差\n到了\n\n2\n00:00:03,000 --> 00:00:04,000\n紙鳶開門\n', encoding='utf-8')
            namespace['filedialog'].askopenfilename.return_value = str(source)
            namespace['filedialog'].asksaveasfilename.return_value = str(output)
            obj = SimpleNamespace(_populate_table=Mock(), trans_btn=Mock(), trans_status=Mock())
            namespace['_import_srt'](obj)
            obj._trans_rows = [(line, SimpleNamespace(get=lambda t=line.text: t)) for line in obj._srt_data]
            namespace['_export_srt'](obj)
            exported = pysubs2.load(str(output))
            self.assertEqual([(s.start, s.end, s.text) for s in exported], [(s.start, s.end, s.text) for s in obj._srt_data])
            namespace['messagebox'].showerror.assert_not_called()


if __name__ == '__main__':
    unittest.main()
