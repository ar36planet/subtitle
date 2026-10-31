# Legacy translation offline regressions

Run from the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install pysubs2
.venv/bin/python -m unittest discover -s tests -v
```

The README documents installation and interactive use, but no test runner. The base contains no existing test files. Only the real SRT dependency (`pysubs2`, validated with 1.9.1) is needed here; unittest is standard library. The suite makes no network requests, downloads no models, needs no GPU, API key, Tk installation, or display. Dependency installation itself needs an available package source or cached wheel.

The notebook loader selects the translation cell by its function definition, compiles its actual definitions/constants using AST, and injects standard modules and an identity progress wrapper. It does not run installation, upload, or transcription cells. End-to-end SRT tests execute the actual translation main flow, replacing file selection, model setup, and translation with fakes. GUI tests import the real module with a minimal fake tkinter and call its existing methods with headless state. No product functions are copied into tests. Fake model/transport modules are scoped and restored using patch.dict.

## Coverage and expectation sources

- Ollama: notebook whole-file and batch calls, global numbering, model/options/system prompt, think-block stripping, ignored out-of-range numbers, one missing-cue retry, original-text fallback and warning, and transport exception propagation. GUI request and output mapping and error/button restoration are checked separately.
- Helsinki: real factories with fake tokenizer/model, CPU and CUDA selection (simulated), 16-item batching, tokenizer arguments, decoding, model-loading and generation failures; GUI cache reuse and errors. No actual torch/transformers packages are imported.
- Glossary: the existing `load_glossary` docstring promises longest terms first. Tests use hand-written fictional pairs to check supported delimiters, empty entries, BOM file handling, file-over-inline duplicate precedence, and longest-first replacement. An unrelated cue remains unchanged. Notebook Helsinki substitutes terms before tokenization; Ollama instead receives exact-term instructions. `check_glossary` is case-insensitive, reports missing requested terms, and ignores unmatched source terms.
- Romaji: the notebook form and `ROMAJI_RULE` specify standard Hepburn for Japanese places/stations/temples/shops/brands/dishes, never Chinese pinyin. Tests assert that instruction and representative documented examples, context and explicit glossary instructions, and disabling the rule. Arbitrary Chinese/non-Japanese text is not locally transliterated. This is a prompt contract, not proof that a real LLM obeys the rule. Existing prompt examples are referenced as rules; all subtitle dialogue and glossary fixture names are invented.
- SRT: the fictional three-cue fixture includes a multiline cue, gaps, and millisecond precision. GUI import/export and actual notebook English/bilingual output are reloaded through real pysubs2. Literal expected text, cue order, count and timestamps are asserted, including preserved original line breaks in bilingual output. Notebook model errors are reported without creating an output file.

## Reproduced base defects (not fixed by this task)

These tests characterize observable defects explicitly; their passing does not certify the goal's new alignment guarantees.

1. `test_known_defect_duplicate_number_silently_overwrites`: `parse_numbered('1: First\n1: Overwritten')` returns only `{0: 'Overwritten'}` without reporting ambiguity. It cannot detect arbitrary semantic misalignment. Notebook retry exhaustion also returns source text with only a printed warning, not an explicit failure marker.
2. `test_known_defect_gui_export_omits_untranslated_rows`: provide three GUI rows with the middle translation empty, then export. The actual exporter emits only the first and third cues, reducing count from three to two. Their timestamps remain intact, but the missing cue is not represented. The desired goal behavior would preserve it with a failure marker.

These are reproducible with the documented suite command, require no external services, and are reported for coordinator follow-up. Product fixes and integration with new modules are outside this task.

## Limits

No pre-existing automated tests were present, so none were skipped or counted as passed. Real Apple Metal transcription, actual Tk rendering/event scheduling, Colab uploads/downloads, actual CUDA/model inference and Ollama service/model installation were not exercised; these require their respective platform/services. GUI callbacks execute immediately in the fake scheduler, so real event-loop timing is not covered. This suite tests the current base directly, without importing alignment or Gemini modules. The separate exported Colab transcription script and older transcription notebook have no tests and are outside the translation paths covered here.
