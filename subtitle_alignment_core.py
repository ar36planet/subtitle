"""Dependency-free ID-based translation validation and bounded repair."""
import json

FAILURE_CODES = {'invalid_response', 'retry_exhausted', 'missing_key', 'backend_error'}


def _validate(response, ids, *, model=False):
    keys = {'items'} if model else {'items', 'failures', 'diagnostics'}
    if not isinstance(response, dict) or set(response) != keys:
        raise ValueError('Invalid response structure')
    if not isinstance(response['items'], list):
        raise ValueError('Invalid items')
    if not model and (
        not isinstance(response['failures'], list)
        or not isinstance(response['diagnostics'], list)
        or any(not isinstance(s, str) for s in response['diagnostics'])
    ):
        raise ValueError('Invalid response structure')
    successes, failures, seen = {}, {}, set()
    groups = [(response['items'], 'text')]
    if not model:
        groups.append((response['failures'], 'code'))
    for rows, field in groups:
        for row in rows:
            if not isinstance(row, dict) or set(row) != {'id', field}:
                raise ValueError('Invalid entry')
            cue_id = row['id']
            if not isinstance(cue_id, str) or cue_id not in ids or cue_id in seen:
                raise ValueError('Ambiguous identity')
            seen.add(cue_id)
            value = row[field]
            if not isinstance(value, str):
                raise ValueError('Invalid value')
            if field == 'text':
                if not value.strip():
                    raise ValueError('Empty translation')
                successes[cue_id] = value
            else:
                if value not in FAILURE_CODES:
                    raise ValueError('Invalid failure code')
                failures[cue_id] = value
    if seen != ids:
        raise ValueError('Incomplete response')
    return successes, failures


def parse_model_response(raw, expected_ids):
    """Require exactly one JSON object, rejecting prose/fences/thinking blocks.

    Invalid schema or identity rejects the whole response. No untrusted text
    or exception details are copied into diagnostics.
    """
    ids = list(expected_ids)
    if any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('Expected IDs must be unique strings')

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result

    try:
        if not isinstance(raw, str):
            raise ValueError('Expected JSON text')
        parsed = json.loads(raw, object_pairs_hook=unique_object)
        successes, _ = _validate(parsed, set(ids), model=True)
    except (ValueError, TypeError, RecursionError):
        return {'items': [], 'failures': [
            {'id': i, 'code': 'invalid_response'} for i in ids
        ], 'diagnostics': ['Invalid model response']}
    return {'items': [{'id': i, 'text': successes[i]} for i in ids],
            'failures': [], 'diagnostics': []}


def translate_cues(cues, backend, *, source_language, target_language,
                   bilingual=False, max_retries=2):
    """Translate a caller-defined batch, preserving metadata and input order.

    Each phase allows 1 + max_retries calls: pending batch, then each unresolved
    singleton for multi-cue input. Backend exceptions never expose details.
    """
    if type(max_retries) is not int or max_retries < 0:
        raise ValueError('max_retries must be a nonnegative integer')
    if not isinstance(source_language, str) or not isinstance(target_language, str):
        raise ValueError('Languages must be strings')
    originals, ids = [], set()
    for cue in cues:
        if not isinstance(cue, dict) or any(
            not isinstance(cue.get(k), str) for k in ('id', 'source', 'start', 'end')
        ):
            raise ValueError('Each cue requires string id, source, start and end')
        if cue['id'] in ids:
            raise ValueError('Cue IDs must be unique')
        ids.add(cue['id'])
        originals.append({k: cue[k] for k in ('id', 'source', 'start', 'end')})
    translated, errors = {}, {}

    def repair(group):
        for _ in range(max_retries + 1):
            pending = [c for c in group if c['id'] not in translated]
            if not pending:
                break
            requested = {c['id'] for c in pending}
            request = {'cues': [{'id': c['id'], 'source': c['source']} for c in pending],
                       'source_language': source_language, 'target_language': target_language}
            try:
                response = backend(request)
            except Exception:
                errors.update({i: 'backend_error' for i in requested})
                continue
            try:
                successes, failures = _validate(response, requested)
            except (ValueError, TypeError, RecursionError):
                errors.update({i: 'invalid_response' for i in requested})
                continue
            translated.update(successes)
            errors.update(failures)

    repair(originals)
    if len(originals) > 1:
        for cue in originals:
            if cue['id'] not in translated:
                repair([cue])
    output, failures = [], []
    for cue in originals:
        cue_id = cue['id']
        if cue_id in translated:
            text = translated[cue_id]
            if bilingual:
                text = cue['source'] + '\n' + text
            status = 'ok'
        else:
            text = cue['source'] + '\n[TRANSLATION_FAILED]'
            status = 'failed'
            failures.append({'id': cue_id, 'code': errors.get(cue_id, 'retry_exhausted')})
        output.append({**cue, 'text': text, 'status': status})
    return {'cues': output, 'failures': failures}
