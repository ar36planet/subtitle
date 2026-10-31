# Gemini subtitle backend

`subtitle_cloud_backend.GeminiBackend` is independent of the GUI, notebooks,
Ollama, Helsinki, and the alignment core. It uses only Python's standard library.
A caller can replace it with any callable implementing the same dictionary contract.
This delivery deliberately leaves application wiring to the coordinator.

```python
from subtitle_cloud_backend import GeminiBackend
backend = GeminiBackend(model='gemini-2.5-flash')
result = backend({
    'cues': [{'id': 'opaque-a', 'source': '月亮郵差\n到了'}],
    'source_language': 'zh', 'target_language': 'en',
})
```

Requests contain unique string ids and multiline sources. Responses contain
`items: [{id, text}]`, `failures: [{id, code}]`, and `diagnostics: [str]`.
Every requested id appears exactly once in items or failures. Failure codes are
`missing_key`, `backend_error`, `retry_exhausted`, and `invalid_response`.
An empty request returns empty lists. Invalid caller ids raise a fixed ValueError.
The caller retains timestamps and order; item position has no meaning.

Model output must be exactly JSON `{"items":[{"id":"opaque-a","text":"translation"}]}`.
Missing/empty entries fail for their ids; duplicated ids fail even if their texts
agree. Unknown ids, extra fields, malformed JSON, duplicate JSON properties,
explanations/thinking, blocked responses, and truncated generations invalidate the
response. Reordered valid ids succeed. Observable merges, splits, and renumbering
are rejected through these checks. Semantic mistranslation under valid ids cannot
be detected reliably. This backend does not retry content; the caller/alignment
core owns bounded content repair.

## Credentials

Only the process environment `GEMINI_API_KEY` or macOS Keychain supplies the key;
a nonempty environment value takes priority. The key is read on each call and is
never persisted by this module. No constructor key parameter exists.

On macOS, use Keychain Access to create a generic password with service/name
`subtitle-gemini` and account `GEMINI_API_KEY`. Enter the password in Keychain
Access's password field. The reader runs `security find-generic-password` with a
five second timeout; it never writes to Keychain. On Linux/Colab it skips Keychain.
A missing/unavailable key returns actionable `missing_key` failures without HTTP.

On Linux, inject the environment from your secret manager, or use a hidden prompt
in a shell (do not enable shell tracing):

```bash
read -r -s -p 'Gemini API key: ' GEMINI_API_KEY
export GEMINI_API_KEY
# Run the calling application in this shell.
unset GEMINI_API_KEY
```

Do not put credentials in files, notebooks, source code, shell command arguments,
or logs. The module sends the key only in the `x-goog-api-key` header to the fixed
HTTPS Google endpoint; redirects are disabled. Remote errors, headers, and
exception messages are never copied into diagnostics. Model text echoing the key
fails validation. Injected transports must likewise avoid logging headers or keys.

## HTTP, retry, and injection

The adapter uses the Gemini REST
[generateContent API](https://ai.google.dev/api/generate-content), requesting one
JSON candidate. `model` is configurable; availability depends on the account.
Default timeout is 30 seconds per HTTP operation, with `max_retries=2` (three
attempts total). Only HTTP 429 is retried. Other HTTP/network errors fail every
requested id with `backend_error`; consecutive 429 exhaustion reports every id
as `retry_exhausted`. No partial translations are inferred from API error bodies.

Retry-After accepts nonnegative numeric seconds or an HTTP date relative to the
injected clock. Gemini `google.rpc.RetryInfo.retryDelay` accepts nonnegative
protobuf duration strings such as `7.5s`. The longest valid server hint wins and
is honored even above the fallback cap. With no valid hint, delays are
`min(backoff_cap, backoff_base * 2**attempt)` (defaults 30 and 1 seconds).
There are at most ten retries; timeout/backoff settings must be positive finite
numbers. Server hints are not capped, so a server can request a long wait; the
attempt budget is finite, not an overall wall time deadline.

Constructor injection points:

- `transport(url, headers, payload, timeout) -> (status, headers, body)` where body
  is JSON bytes or a string. Transport exceptions become generic failures.
- `sleep(seconds)` and `clock() -> Unix seconds` enable deterministic retry tests.
- `keychain_reader(service, account) -> str | None` replaces the default macOS
  lookup. It is only called when the environment key is absent/empty.

## Offline verification

```bash
python3 -m venv .venv
.venv/bin/python -m pip install pysubs2
.venv/bin/python -m unittest discover -s tests -v
```

All API tests use fake responses and generated fictitious keys. All subtitle
fixtures are invented. Tests require no GPU, network access, actual credentials,
Tk display, or models. `pysubs2` is needed only for the regression test executing
the existing SRT import/export methods without constructing the GUI.
