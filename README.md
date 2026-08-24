# handbrake

> A zero-config static gate that flags an **autonomous LLM agent wired to a
> destructive tool with no human in the loop** — a tool that can delete data,
> move money, message customers, run a shell command, or deploy, invoked by the
> agent on its own with no approval step. AST-based, zero config. Meant to run
> in CI.

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Autonomous agents connected to irreversible actions with no human-in-the-loop
is one of the top agentic-AI risks of 2025-26. You give an agent a set of tools
and let it decide which to call. Most tools are harmless — read a record, search
a doc. But one of them runs `DELETE FROM customers`, issues a Stripe refund,
sends an email to a customer, or shells out to `kubectl`. If nothing sits
between the model's decision and that action — no approval, no confirmation, no
human-in-the-loop — then a single bad plan step deletes the row, moves the
money, or sends the message, autonomously and irreversibly.

`handbrake` reads your source with Python's `ast` module — it never imports or
runs your code — and fails the build when it finds a destructive tool exposed to
an autonomous agent with no approval gate:

```text
$ handbrake agent.py

╭─ BLOCKER HB001 ──────────────────────────────────────────────────────────────────╮
│ agent.py:25:1                                                                      │
│ the destructive tool 'delete_customer' is exposed to an autonomous agent/executor  │
│ with no human-approval, confirmation, or human-in-the-loop gate anywhere — the     │
│ agent can invoke a delete/payment/send/deploy/shell action on its own, with no one  │
│ able to stop it, and the effect is irreversible.                                    │
│ Fix: Put a human in the loop before the destructive action: gate the tool behind    │
│ an approval/confirmation step (LangGraph interrupt, an approval tool, AutoGen       │
│ human_input_mode, a require_approval/dry_run flag, or an allow-list) …              │
╰────────────────────────────────────────────────────────────────────────────────────╯
```

## Why static / why CI

An ungated destructive tool doesn't raise an exception — the code is valid, and
in the demo the agent politely calls the read-only tools. It bites you on the
one production run where the model reasons its way into calling the delete tool,
and by then the row is gone. A static gate on the pull request catches the
missing approval before it ships, with no runtime, no API key, and no execution
of your code.

## What it flags

| Rule | Severity | Risk | The fix |
| --- | --- | --- | --- |
| `HB001` | blocker | A **destructive/irreversible tool is exposed to an autonomous agent/executor** with **no** approval / confirmation / human-in-the-loop gate anywhere — the tool is registered (LangChain `@tool` / `Tool(...)`, CrewAI, AutoGen `register_*`, LlamaIndex `FunctionTool`, or an OpenAI/Anthropic `tools=[...]` list) and an agent/executor is constructed in the same file. | Gate the destructive tool behind a human-approval / confirmation / HITL step, or remove it from the autonomous tool set. |
| `HB002` | warn | A **destructive agent tool is defined** with an agent framework present, but its **wiring/approval state is uncertain** — no agent/executor construction is visible in this file. | Confirm the tool is only reachable behind an approval gate; suppress if it is gated elsewhere. |

**What counts as destructive.** A tool whose name carries a destructive verb
(`delete` / `drop` / `remove` / `terminate` / `charge` / `refund` / `send` /
`deploy` / `exec` / `overwrite` …) **or** whose body performs a destructive
operation — `os.remove` / `shutil.rmtree`, a `subprocess` call, `requests.delete`
/ a write-mode HTTP call, a write-mode `open(...)`, or a `DROP`/`DELETE` SQL (or
`rm -rf`) string.

**What never fires.** Read-only tools — `get` / `list` / `search` / `read` /
`fetch` / `query` / `describe` … — are never flagged. And any
approval / confirmation / human-in-the-loop marker in the file short-circuits
`HB001` to clean: `human_input`, `require_approval`, `interrupt` (LangGraph),
`confirm`, `HumanApproval`, `dry_run`, an allow-list, and more. (AutoGen's
`human_input_mode="NEVER"` is *not* treated as a gate — that setting is exactly
the autonomous one.)

`handbrake` engages **only when an agent framework is imported** (`langchain`,
`crewai`, `autogen`, `llama_index`, `langgraph`, `openai`, `anthropic`). A file
that imports none of them is never flagged.

## Before / after

```python
# UNGATED — the agent can delete on its own (HB001):
@tool
def delete_customer(cid):
    db.execute("DELETE FROM customers WHERE id = ?", cid)

agent = create_tool_calling_agent(llm, [delete_customer], prompt)
executor = AgentExecutor(agent=agent, tools=[delete_customer])

# GATED — a human approves before the irreversible action:
@tool
def delete_customer(cid):
    if interrupt({"action": "delete", "id": cid}) != "approved":
        return "cancelled by reviewer"
    db.execute("DELETE FROM customers WHERE id = ?", cid)
```

## Install

```bash
pip install handbrake
```

## Usage

```bash
handbrake agent.py               # scan one file
handbrake src/                   # recurse a directory (skips vendor/build/caches)
handbrake src/ --json            # machine-readable output for CI
handbrake src/ --strict          # also fail on HB002 uncertain-wiring warnings
handbrake agent.py --no-color    # plain text
```

Exit codes: **0** clean · **1** blocker (or any finding under `--strict`) · **2** usage error.

Scanned extensions: `.py` (AST-based). Files over 2 MiB and vendored/build
directories are skipped. Suppress a line with a trailing `# handbrake: ignore`
(or `# noqa: HB001`), or exclude paths with `--exclude GLOB` (repeatable) or a
`.handbrakeignore` file (gitignore-style globs).

## In CI

```yaml
- name: No-human-in-the-loop gate
  run: |
    pip install handbrake
    handbrake src/
```

## pre-commit

```yaml
- repo: local
  hooks:
    - id: handbrake
      name: handbrake
      entry: handbrake
      language: system
      types: [python]
```

## How it fits with the rest of the family

`handbrake` is about **destructive action with no approval** — distinct from
[`itercap`](https://github.com/jay-tank/itercap) (an agent with no iteration/turn
cap — runaway *loops*), `mcpwary` (auditing an MCP server's advertised tools),
and `toolens` (tool-description quality). handbrake asks one question the others
don't: *can this agent do something irreversible without asking a human first?*

## Companion practice: log the resolved model, not the requested one

An approval gate answers *"should this run?"*; provenance answers *"which model
actually decided it?"* — and in an incident you want both. When you wire the
human-in-the-loop gate handbrake asks for, log the model identity **alongside every
destructive tool call** so the decision is reproducible after the fact.

One nuance worth getting right: log the **resolved** model id from the *response
payload* (what the provider says served the call), not the model you *requested*.
On routers, gateways, and after a fallback the two diverge — and the response field
is the only one that's still true once a fallback has happened. Capture it together
with the endpoint/gateway that served the request:

```python
resp = client.chat.completions.create(model="gpt-4o", messages=...)
log.info("tool_call", tool="delete_account", approved_by=user,
         requested_model="gpt-4o",
         resolved_model=resp.model)   # <- the fact; may differ after a fallback
```

handbrake stays static — it gates the missing approval at the PR, before anything
runs — so this runtime provenance is the complementary half of the same safety story,
not something handbrake enforces itself. (Thanks to a reader for sharpening this point.)

## Limitations (honest)

`handbrake` is a static, name/shape-based heuristic. Destructiveness is inferred
from the tool's name and the calls in its body, so a tool that deletes through an
opaque helper it can't see may be under-reported, and an unusual but harmless
call shape could be over-reported (suppress those with `# handbrake: ignore`).
Registration is detected from decorators, `Tool(...)`/`FunctionTool` wrappers,
and `tools=[...]` lists — a tool injected through `**kwargs` or assembled
dynamically is invisible. The approval check is file-scoped: any recognized
approval/HITL marker in the file clears `HB001`, so an approval marker that is
present but not actually wired to *this* tool can hide a real gap (a deliberate
low-false-positive tradeoff). It never executes your code.

> 📖 Read the write-up: [handbrake](https://jaytank.hashnode.dev/handbrake-agent-approval-gate)

## License

MIT — see [LICENSE](LICENSE).
