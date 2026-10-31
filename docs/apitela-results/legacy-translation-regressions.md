# Result

Completed the scoped legacy regression deliverable without modifying product code, planning files, or `.task/`.

Changed areas:

- `tests/test_legacy_translation_regressions.py`: 15 offline unittest tests against existing GUI methods and notebook translation code, with fake Ollama/Helsinki/Tk dependencies.
- `tests/fixtures/legacy_translation_regressions/imaginary.srt`: entirely fictional multiline, three-cue subtitle fixture.
- `docs/legacy_translation_regressions.md`: execution instructions, behavioral expectations, coverage, reproducible base defects and limits.

Read both files in `.task/` and README development instructions. No AGENTS.md or existing automated tests/test configuration were found. README has installation/use commands, not a test command. The Apple-specific full requirements were not installed; only the real SRT library needed for these offline tests was installed in the required local venv.

## Commands and results

- `python3 -m venv .venv` — exit 0.
- `.venv/bin/python -m pip install pysubs2` — exit 0; installed 1.9.1.
- `.venv/bin/python -m unittest discover -s tests -v` (initial run) — exit 1; 9 notebook tests passed; GUI setup failed because Linux lacks tkinter.
- Same command (after injecting fake Tk) — exit 1; 14 tests ran, two failures exposed an incomplete fake tokenizer mapping. Corrected the fake input to support both mapping expansion and `.to(device)`.
- Same command (after correcting fake) — exit 0; 14 tests passed.
- Same command (final suite including additional defect reproduction and romaji examples) — exit 0; all 15 tests passed, no skips, no model/GPU/network/key required during tests.

All discovered offline tests are included in the final discovery run. There were no pre-existing tests to execute. Actual GUI rendering/event scheduling, Apple Metal transcription, Colab integration, real Ollama/Helsinki inference, and real CUDA execution were not run and are not claimed as passed. See the coverage document for individual limits.

## Findings and unresolved items

No delivery blocker. Existing defects are documented and reproduced without changing product behavior: duplicate model numbers silently overwrite earlier translations, and GUI SRT export drops rows with empty translations. Notebook exhausted missing-cue retries preserve source text with a warning rather than a failure marker. Passing characterization tests do not certify the new goal's alignment guarantees. Romaji is an LLM prompt instruction, not a deterministic local transliterator; offline tests verify its wording, scope and toggle, not model compliance. Product fixes and integration remain outside this task's explicit scope.

- `git diff --check` — exit 0; no tracked diff whitespace errors (new deliverables are untracked until wrapper publication).
