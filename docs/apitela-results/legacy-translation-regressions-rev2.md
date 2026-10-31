# Result

Implemented the three scoped legacy fixes without introducing alignment-core or
cloud interfaces.

- `transcriber.py`: validate each numbered Ollama batch before assigning results;
  reject duplicate or out-of-batch numbers instead of overwriting translations.
  Unresolved entries retain source text with `[TRANSLATION_FAILED]`. Export every
  GUI row, including empty/whitespace translations, with the same failure fallback.
- `colab_transcribe.ipynb`: reject duplicate-number responses, retain the existing
  bounded repair attempt, and mark exhausted entries. The output loop restores
  the original multiline source for failed cues in both output styles.
- `tests/test_legacy_translation.py`: 12 offline tests, including distinct
  regressions for duplicates, mixed blank/successful exports, and repeated
  notebook failure; SRT timing/order/count, multiline, both output styles,
  successful Ollama/Helsinki, glossary priority/replacement/unmatched terms, and
  romaji prompt scope and enable/disable behavior. All subtitle data is fictional.
- `tests/README.md`: offline execution and test isolation details.

## Commands and results

- `python3 -m venv .venv` — exit 0.
- `.venv/bin/python -m pip install pysubs2` — exit 0; installed 1.9.1 in `.venv`.
- `.venv/bin/python /tmp/fix_legacy.py` — exit 0; scoped edits.
- `.venv/bin/python -m unittest discover -s tests -v` — initial exit 1:
  Linux lacks tkinter. Added a headless import stub in tests only.
- Same unittest command after stub — exit 0, 8 tests passed.
- `.venv/bin/python /tmp/add_tests.py` — exit 0; added file-loop and Helsinki tests.
- Same unittest command — exit 0, 10 tests passed.
- `.venv/bin/python /tmp/final_tests.py` — exit 0; added romaji boundary and whole-file retry checks.
- Same unittest command, final run — exit 0, all 12 tests passed.
- `.venv/bin/python -m compileall -q transcriber.py tests` — exit 0.
- `git diff --check` — exit 0 (both runs).

## Limits and unresolved questions

No blockers. The base contains no existing tests, characterization suite, or
specified test command; README documents application setup only. No existing
tests were skipped or reported as passed. The unrelated v2 transcription files
contain no translation path and were unchanged.

Real macOS Tk interaction, mlx-whisper/Metal, live Ollama, real Helsinki weights,
and full Colab GPU/upload/download execution were not run: they require platform,
models, or external services absent from this offline Linux verification. Tests
exercise the actual translation/export methods with fakes. Romaji is only a
prompt rule in the base; tests verify prompt rules and unchanged source text,
not real-model linguistic accuracy. Broader alignment and cloud work remains
outside this task as specified.
