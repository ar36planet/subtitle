Run offline regressions from the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install pysubs2==1.9.1
.venv/bin/python -m unittest discover -s tests -v
```

Only pysubs2 is required. Tests use unittest, fake Ollama/Transformers/Torch,
and a Tk import stub when Tk is unavailable. They never create widgets, load a
model, use credentials, download files, or contact services. All cue content is
fictional and embedded in the tests.

Notebook tests extract definitions/constants with AST and execute the actual
SRT processing loop separately; installation, Colab, upload/download, and model
startup code never executes. Round trips check cue count/order/timing and
multiline originals. Duplicate numbers invalidate the complete response batch;
the notebook retains its existing one repair attempt, while GUI failures are
marked immediately.

The base has no test suite or characterization tests. These tests establish
corrected characterizations and add explicit regressions for all three defects.
Romaji is a prompt instruction in the base, not a deterministic converter: tests
check its Japanese proper-noun scope, example, enable/disable behavior, and that
source text is not rewritten. Fake responses cannot verify real model semantics.
