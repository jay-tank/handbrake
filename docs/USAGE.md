# handbrake — Usage

`handbrake` is a zero-config static gate for the **no-human-in-the-loop**
agent footgun — an autonomous LLM agent wired to a destructive or irreversible
tool with no approval, confirmation, or human-in-the-loop step. It parses source
with the standard-library `ast` module and **never imports or executes the
target code**, so it is safe to run over untrusted source in CI.

## Command

```
handbrake [PATHS ...] [--strict] [--json] [--no-color] [--exclude GLOB] [--version] [-h]
```

- `PATHS` — one or more files or directories. Directories are walked
  recursively; vendored/build/cache directories (`node_modules`, `vendor`,
  `build`, `dist`, `.venv`, `target`, …) are skipped.
- `--strict` — also fail (exit 1) on `HB002` warnings, not just blockers.
- `--json` — emit machine-readable JSON instead of the terminal report.
- `--no-color` — disable ANSI colour (useful for logs / CI).
- `--exclude GLOB` — exclude matching paths; repeatable.
- `--version` — print the version and exit.
- `-h`, `--help` — show help.

Only `.py` files are read and analysed (precise, AST-based). Files larger than
2 MiB are skipped.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | No blocking findings (HB002 warnings alone pass unless `--strict`). |
| `1` | One or more blockers (HB001), or any finding under `--strict`. |
| `2` | Usage error — no paths given, or no scannable files found. |

Files that fail to parse (Python syntax errors) or can't be read are reported
on stderr and skipped; they don't crash the run.

## When handbrake engages

handbrake stays completely silent unless the file imports an agent framework —
`langchain` (and its sub-packages), `langgraph`, `crewai`, `autogen` /
`pyautogen`, `llama_index`, `openai`, or `anthropic`. A plain script that just
happens to define a `delete_file` function is never flagged.

## The decision, step by step

For each function defined in an engaged file, handbrake asks:

1. **Is it registered as an agent tool?** Decorated with `@tool` /
   `@function_tool` / AutoGen `register_*`, wrapped in `Tool(...)` /
   `StructuredTool.from_function` / `FunctionTool.from_defaults`, or referenced
   in a `tools=[...]` list. If not, it is ignored.
2. **Is it destructive?** Its name carries a destructive verb (`delete`, `drop`,
   `remove`, `terminate`, `charge`, `refund`, `send`, `deploy`, `exec`,
   `overwrite`, …), or its body performs a destructive operation (`os.remove`,
   `shutil.rmtree`, a `subprocess` call, `requests.delete` / a write-mode HTTP
   call, a write-mode `open(...)`, or a `DROP`/`DELETE` SQL / `rm -rf` string).
   Plainly read-only tools (`get`/`list`/`search`/`read`/…) are never
   destructive.
3. **Is there an approval gate anywhere in the file?** Any of `human_input`,
   `require_approval`, `interrupt`, `confirm`, `HumanApproval`,
   `human_in_the_loop`, `dry_run`, an allow-list, and similar. If so, the tool
   is treated as gated → clean. (AutoGen's `human_input_mode="NEVER"` does *not*
   count — it is the autonomous setting.)
4. **Is an autonomous agent/executor constructed in this file?**
   `AgentExecutor`, `initialize_agent`, `create_*_agent`, `Crew`,
   `initiate_chat`, `AgentRunner`, `ReActAgent`, or a run/create call that passes
   `tools=`.

- Destructive + registered + no approval + executor present → **HB001** (blocker).
- Destructive + registered + no approval + no executor visible → **HB002** (warn).

## Suppression

- Inline: add `# handbrake: ignore` or `# noqa: HB001` to the flagged line (the
  tool's `def` line).
- Per-path: pass `--exclude 'GLOB'` (repeatable) or add gitignore-style globs to
  a `.handbrakeignore` file in the working directory.
