# Contributing to handbrake

Thanks for your interest! handbrake is a small, focused static gate, and the bar
for a change is simple: it should make the check catch a real no-human-in-the-loop
agent risk without adding false positives.

## Development

```bash
git clone https://github.com/jay-tank/handbrake
cd handbrake
pip install -e '.[dev]'
python -m pytest -q
```

The code is four flat modules at the repo root:

- `scanner.py` — the AST analysis (destructiveness, tool registration, executor
  detection, approval markers). Never imports or executes target code.
- `models.py` — `Finding` / `ScanResult` dataclasses and the rule codes.
- `render.py` — terminal (`rich`) and `--json` output.
- `cli.py` — argument parsing, file walking, exit codes.

## Guidelines

- **Every behaviour change needs a test** — a true positive and, where relevant,
  a clean case that must stay quiet. handbrake lives or dies on its
  false-positive rate.
- **Prefer under-reporting to over-reporting.** A missed edge case is a follow-up;
  a noisy false positive gets the tool removed from CI.
- Keep it dependency-light (`rich` only at runtime) and Python 3.9+ compatible.
- Extending detection is welcome: more frameworks, more destructive call shapes,
  more approval/HITL markers. Add them to the tables in `scanner.py` with a test.

## Reporting issues

Please include a minimal source snippet that reproduces the false positive or
false negative, and what you expected. That snippet usually becomes the
regression test.
