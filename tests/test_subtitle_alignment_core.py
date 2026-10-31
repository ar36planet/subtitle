"""All subtitle examples are fictional; no service/model/GPU is used."""
import copy
import json
import unittest

from subtitle_alignment_core import parse_model_response, translate_cues


def cues():
    return [
        {'id': 'opaque-moon', 'source': '月亮郵差到了。',
         'start': '00:00:01,000', 'end': '00:00:02,000'},
        {'id': 'opaque-tea', 'source': '雲朵茶\n準備好了。',
         'start': '00:00:02,500', 'end': '00:00:04,000'},
        {'id': 'opaque-boat', 'source': '紙船開始唱歌。',
         'start': '00:00:05,000', 'end': '00:00:06,000'},
    ]


TEXT = {'opaque-moon': 'The moon courier arrived.',
        'opaque-tea': 'Cloud tea\nis ready.',
        'opaque-boat': 'The paper boat starts singing.'}


def good(request):
    return {'items': [{'id': c['id'], 'text': TEXT[c['id']]}
                      for c in reversed(request['cues'])],
            'failures': [], 'diagnostics': []}


def run(data, backend, **kwargs):
    return translate_cues(data, backend, source_language='zh', target_language='en', **kwargs)


class AlignmentTests(unittest.TestCase):
    def assert_aligned(self, result, original, bilingual=False):
        self.assertEqual(result['failures'], [])
        self.assertEqual(len(result['cues']), len(original))
        for before, after in zip(original, result['cues']):
            for key in ('id', 'source', 'start', 'end'):
                self.assertEqual(after[key], before[key])
            expected = TEXT[before['id']]
            if bilingual:
                expected = before['source'] + '\n' + expected
            self.assertEqual(after['text'], expected)
            self.assertEqual(after['status'], 'ok')

    def test_full_batch_single_multiline_empty_and_bilingual(self):
        for data in ([], cues()[:1], cues()[1:2], cues()):
            for bilingual in (False, True):
                with self.subTest(count=len(data), bilingual=bilingual):
                    original = copy.deepcopy(data)
                    calls = []
                    def backend(request):
                        calls.append(request)
                        self.assertEqual(set(request), {'cues', 'source_language', 'target_language'})
                        self.assertEqual(request['source_language'], 'zh')
                        self.assertEqual(request['target_language'], 'en')
                        self.assertTrue(all(set(c) == {'id', 'source'} for c in request['cues']))
                        return good(request)
                    self.assert_aligned(run(data, backend, bilingual=bilingual), data, bilingual)
                    self.assertEqual(data, original)
                    self.assertEqual(len(calls), int(bool(data)))

    def test_model_errors_detected_and_batch_retry_repairs(self):
        items = good({'cues': cues()})['items']
        # Equal-count duplicate/unknown/renumbered outputs cannot pass by length.
        errors = {
            'merge': {'items': [{'id': 'opaque-moon', 'text': 'Courier arrived. Tea ready.'}, items[0]]},
            'split': {'items': items + [{'id': 'opaque-tea', 'text': 'Ready.'}]},
            'missing': {'items': items[:-1]},
            'renumbered': {'items': [{'id': str(i), 'text': t['text']} for i, t in enumerate(items)]},
            'duplicate': {'items': [items[0], items[0], items[2]]},
            'unknown': {'items': [items[0], items[1], {'id': 'foreign', 'text': 'Other.'}]},
            'empty': {'items': [items[0], items[1], {'id': items[2]['id'], 'text': ' \n'}]},
            'structure': {'items': {'id': 'opaque-moon', 'text': 'Hello'}},
        }
        raw_errors = {k: json.dumps(v) for k, v in errors.items()}
        valid = json.dumps({'items': items})
        raw_errors.update({
            'explanation': 'Here is the translation: ' + valid,
            'thinking': '<think>Consider the moon.</think>' + valid,
            'truncated': valid[:-8],
            'fenced': '```json\n' + valid + '\n```',
            'trailing': valid + '\nDone.',
            'duplicate-json-key': '{"items": [], "items": ' + json.dumps(items) + '}',
        })
        for name, raw in raw_errors.items():
            with self.subTest(name=name):
                invalid = parse_model_response(raw, [c['id'] for c in cues()])
                self.assertEqual(invalid['items'], [])
                self.assertEqual(invalid['failures'], [
                    {'id': c['id'], 'code': 'invalid_response'} for c in cues()])
                calls = []
                def backend(request):
                    calls.append(request)
                    return invalid if len(calls) == 1 else good(request)
                self.assert_aligned(run(cues(), backend, max_retries=1), cues())
                self.assertEqual(len(calls), 2)
        self.assertEqual(parse_model_response(valid, TEXT)['failures'], [])

    def test_singleton_fallback_and_limits(self):
        for retries in (0, 1, 2):
            calls = []
            def backend(request):
                calls.append(request)
                if len(request['cues']) > 1:
                    return None
                return good(request)
            self.assert_aligned(run(cues(), backend, max_retries=retries), cues())
            self.assertEqual(len(calls), retries + 1 + len(cues()))
            for singleton in (False, True):
                data = cues()[:1] if singleton else cues()
                calls.clear()
                def broken(request):
                    calls.append(request)
                    return {'items': [{'id': 'wrong', 'text': 'Wrong translation'}],
                            'failures': [], 'diagnostics': []}
                result = run(data, broken, max_retries=retries)
                bound = (retries + 1) * (1 if singleton else len(data) + 1)
                self.assertEqual(len(calls), bound)
                self.assertEqual(result['failures'], [
                    {'id': c['id'], 'code': 'invalid_response'} for c in data])
                for before, after in zip(data, result['cues']):
                    self.assertEqual(after, {**before, 'text': before['source'] + '\n[TRANSLATION_FAILED]',
                                             'status': 'failed'})

    def test_successes_never_retried_or_overwritten(self):
        calls = []
        def backend(request):
            calls.append([c['id'] for c in request['cues']])
            if len(calls) == 1:
                return {'items': [{'id': 'opaque-moon', 'text': TEXT['opaque-moon']}],
                        'failures': [{'id': c['id'], 'code': 'retry_exhausted'} for c in cues()[1:]],
                        'diagnostics': []}
            self.assertNotIn('opaque-moon', calls[-1])
            if len(calls) == 2:
                return {'items': [], 'failures': [
                    {'id': c['id'], 'code': 'backend_error'} for c in request['cues']], 'diagnostics': []}
            return good(request)
        self.assert_aligned(run(cues(), backend, max_retries=1), cues())
        self.assertEqual(calls, [list(TEXT), list(TEXT)[1:], ['opaque-tea'], ['opaque-boat']])

    def test_batch_boundary_foreign_id_is_rejected(self):
        data = cues()
        results = []
        for batch in (data[:2], data[2:]):
            calls = []
            def backend(request):
                calls.append(request)
                if len(calls) == 1:
                    return good({'cues': data})  # Leaked context from a different batch.
                return good(request)
            result = run(batch, backend, max_retries=1)
            self.assertEqual(len(calls), 2)
            results.extend(result['cues'])
        self.assert_aligned({'cues': results, 'failures': []}, data)

    def test_backend_contract_rejects_malformed_responses(self):
        valid = good({'cues': cues()[:1]})
        cases = [None, {}, {'items': valid['items']},
                 {**valid, 'diagnostics': 'wrong'}, {**valid, 'failures': None},
                 {**valid, 'items': [None]},
                 {**valid, 'failures': [{'id': 'opaque-moon', 'code': 'backend_error'}]},
                 {**valid, 'items': [], 'failures': [{'id': 'opaque-moon', 'code': 'invented'}]},
                 {**valid, 'items': [], 'failures': valid['items']},
                 {**valid, 'items': [{'id': 'opaque-moon', 'text': ''}]},
                 {**valid, 'items': []},
                 {**valid, 'items': [{'id': 'opaque-moon', 'text': 'Good', 'extra': True}]}]
        for response in cases:
            with self.subTest(response=response):
                result = run(cues()[:1], lambda _: response, max_retries=0)
                self.assertEqual(result['failures'][0]['code'], 'invalid_response')

    def test_exceptions_and_backend_failure_codes(self):
        def broken(_):
            raise RuntimeError('untrusted exception detail')
        result = run(cues()[:1], broken, max_retries=0)
        self.assertEqual(result['failures'][0]['code'], 'backend_error')
        self.assertNotIn('untrusted', repr(result))
        for code in ('missing_key', 'backend_error', 'retry_exhausted', 'invalid_response'):
            result = run(cues()[:1], lambda _: {
                'items': [], 'failures': [{'id': 'opaque-moon', 'code': code}],
                'diagnostics': []}, max_retries=0)
            self.assertEqual(result['failures'][0]['code'], code)

    def test_singleton_retry_and_partial_final_failure(self):
        calls = []
        def retry_single(request):
            calls.append(request)
            if len(calls) == 1:
                return {'items': [], 'failures': [], 'diagnostics': []}
            return good(request)
        self.assert_aligned(run(cues()[1:2], retry_single, max_retries=1), cues()[1:2])
        self.assertEqual(len(calls), 2)

        calls.clear()
        def partial(request):
            calls.append([c['id'] for c in request['cues']])
            return {'items': [row for row in good(request)['items']
                              if row['id'] != 'opaque-tea'],
                    'failures': [{'id': 'opaque-tea', 'code': 'retry_exhausted'}],
                    'diagnostics': []}
        result = run(cues(), partial, max_retries=1)
        self.assertEqual(calls, [list(TEXT), ['opaque-tea'], ['opaque-tea'], ['opaque-tea']])
        self.assertEqual(result['failures'], [{'id': 'opaque-tea', 'code': 'retry_exhausted'}])
        for index in (0, 2):
            self.assert_aligned({'cues': [result['cues'][index]], 'failures': []}, [cues()[index]])
        failed = result['cues'][1]
        self.assertEqual(failed['status'], 'failed')
        self.assertEqual(failed['text'], cues()[1]['source'] + '\n[TRANSLATION_FAILED]')

    def test_input_validation_and_isolation_from_backend_mutation(self):
        for retries in (-1, 1.5, True):
            with self.assertRaises(ValueError):
                run(cues(), good, max_retries=retries)
        for data in ([cues()[0], cues()[0]], [{'id': 'a'}], [{**cues()[0], 'id': []}]):
            with self.assertRaises(ValueError):
                run(data, good)
        data = cues()
        def mutate(request):
            response = good(request)
            request['cues'][0]['source'] = 'Changed'
            return response
        self.assert_aligned(run(data, mutate), cues())
        self.assertEqual(data, cues())
        with self.assertRaises(ValueError):
            parse_model_response('{}', ['same', 'same'])


if __name__ == '__main__':
    unittest.main()
