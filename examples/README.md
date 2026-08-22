# Examples

Two versions of the same agent: one that can delete a customer on its own, and
one that asks a human first.

## `ungated.py` — a finding, exits 1

```bash
handbrake examples/ungated.py
```

Flags a blocker (`HB001`): a `delete_customer` tool that runs
`DELETE FROM customers ...` is registered as an agent tool and wired into an
`AgentExecutor`, with **no** approval, confirmation, or human-in-the-loop gate
anywhere. If the model decides to call it, the row is gone — autonomously and
irreversibly.

The `get_customer` tool right beside it is **read-only**, so handbrake never
flags it. That destructive-vs-read-only distinction is the whole point of the
tool.

## `gated.py` — clean, exits 0

```bash
handbrake examples/gated.py
```

The same logic, fixed. A LangGraph `interrupt` puts a human in the loop before
`delete_customer` runs, and the tool takes a `require_approval` gate. Because an
approval / human-in-the-loop marker is present, handbrake treats the destructive
tool as gated and reports nothing.
