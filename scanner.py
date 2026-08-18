"""Scanner for the no-human-in-the-loop agent footgun.

The scanner parses source with the standard-library ``ast`` module and
**never imports or executes the target code**. It flags a top 2025-26 agentic
risk: an autonomous LLM agent wired to a **destructive or irreversible** tool
(delete/drop, payments/refunds, send message/email, external POST/PUT/DELETE,
shell/exec, file overwrite, deploy) with **no human-approval / confirmation /
human-in-the-loop gate** anywhere. When the agent decides on its own to call
that tool, nobody is there to stop it — data gets deleted, money moves, or a
customer is messaged, autonomously and irreversibly.

Rules:
  HB001 (blocker) — a DESTRUCTIVE tool is registered as an agent tool AND an
      autonomous agent/executor is constructed in the same file, and there is
      NO approval / confirmation / human-in-the-loop guard anywhere (no
      ``human_input``, ``require_approval``, ``interrupt``, ``confirm``,
      ``HumanApproval``, ``dry_run``, or an allow-list).
  HB002 (warn)    — a DESTRUCTIVE tool is registered as an agent tool with an
      autonomous framework present, but its wiring/approval state is uncertain
      (no explicit agent/executor construction is visible in this file).

Detection strategy (documented, honest heuristic): the scanner engages only
when an agent framework is imported (``langchain`` / ``crewai`` / ``autogen`` /
``llama_index`` / ``openai`` / ``anthropic`` / ``langgraph``) — otherwise it
stays silent. A tool is "destructive" when its name carries a destructive verb
(delete/drop/rm/terminate/charge/refund/send/deploy/exec/overwrite…) or its
body performs a destructive operation (``os.remove`` / ``shutil.rmtree`` /
``subprocess`` / ``requests.delete`` / a write-mode ``open`` / a ``DROP``/
``DELETE`` SQL string…). Read-only tools (``get``/``list``/``search``/``read``
…) never fire. A tool is "registered" when it is decorated with an agent
``@tool`` (or ``@function_tool`` / AutoGen ``register_*``), wrapped in a
``Tool(...)`` / ``StructuredTool.from_function`` / ``FunctionTool.from_defaults``
constructor, or referenced inside a ``tools=[...]`` list. The presence of any
approval/HITL marker in the file short-circuits HB001 to clean. The analysis is
name/shape based: it cannot follow a tool passed through ``**kwargs`` or an
approval gate hidden behind an opaque call.
"""

from __future__ import annotations

import ast
import os
import re
from typing import Dict, List, Optional, Set, Tuple

from models import BLOCKER, HB001, HB002, WARN, Finding

# Inline suppression: either marker on a flagged line skips it.
INLINE_IGNORE = "handbrake: ignore"
NOQA = "noqa"

# ---------------------------------------------------------------------------
# Framework gating — engage only when an agent framework is imported
# ---------------------------------------------------------------------------
_AGENT_FRAMEWORKS = {
    "langchain", "langchain_core", "langchain_community", "langchain_experimental",
    "langgraph", "crewai", "autogen", "pyautogen", "llama_index", "llama_index",
    "openai", "anthropic", "agents",
}


def _root_module(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    return name.split(".", 1)[0]


def _uses_agent_framework(tree: ast.Module) -> bool:
    """True if the module imports one of the recognised agent frameworks."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _root_module(alias.name) in _AGENT_FRAMEWORKS:
                    return True
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and _root_module(node.module) in _AGENT_FRAMEWORKS:
                return True
    return False


# ---------------------------------------------------------------------------
# Destructive tool detection
# ---------------------------------------------------------------------------
# Destructive verbs, matched against the word tokens of a function name.
_DESTRUCTIVE_NAME_TOKENS = {
    "delete", "del", "destroy", "drop", "remove", "rm", "purge", "wipe",
    "truncate", "erase", "terminate", "kill", "shutdown", "revoke", "cancel",
    "uninstall", "reset", "overwrite", "prune",
    "refund", "charge", "pay", "payment", "payout", "transfer", "chargeback",
    "send", "email", "sms", "notify", "message", "post", "publish", "tweet",
    "deploy", "release", "rollout", "provision", "exec", "execute", "shell",
    "run", "spawn", "format", "ban", "suspend", "unsubscribe",
}
# Read-only verbs. A tool whose name carries one of these (and no destructive
# verb, and no destructive body op) never fires — this is the low-FP guarantee.
_READONLY_NAME_TOKENS = {
    "get", "list", "search", "read", "fetch", "find", "query", "describe",
    "show", "view", "count", "lookup", "load", "retrieve", "check", "peek",
    "inspect", "summarize", "summarise", "analyze", "analyse", "detect",
    "classify", "translate", "calculate", "compute",
}

_WORD_SPLIT = re.compile(r"[^a-z0-9]+")


def _name_tokens(name: str) -> Set[str]:
    """Split ``deleteUserAccount`` / ``delete_user`` into {delete, user, account}."""
    # camelCase -> snake, then split on non-alphanumerics.
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return {t for t in _WORD_SPLIT.split(snake.lower()) if t}


# Method attributes that, when called, mean a destructive side effect.
_DESTRUCTIVE_ATTRS = {
    "remove", "unlink", "rmdir", "removedirs", "rmtree", "system",
    "delete", "drop", "terminate", "truncate", "destroy", "purge", "kill",
    "deploy", "refund", "charge", "revoke", "sendmail", "send_message",
    "send_email", "expire", "cancel",
}
# subprocess-family: destructive when the root is a process module.
_SUBPROCESS_ATTRS = {"run", "call", "check_call", "check_output", "Popen", "getoutput"}
_SUBPROCESS_ROOTS = {"subprocess", "sp", "commands"}
# HTTP write verbs: destructive when the root looks like an HTTP client.
_HTTP_ATTRS = {"post", "put", "patch", "delete"}
_HTTP_ROOTS = {"requests", "httpx", "session", "client", "http", "aiohttp", "urllib3"}
# SQL / shell danger inside a string constant.
_DANGER_STR = re.compile(
    r"\b(drop\s+table|delete\s+from|truncate\s+table|drop\s+database)\b|rm\s+-rf",
    re.IGNORECASE,
)
# open(...) modes that write / overwrite / append.
_WRITE_MODES = {"w", "wb", "w+", "wt", "a", "ab", "a+", "x", "xb"}


def _root_name(node: ast.AST) -> Optional[str]:
    """Leftmost Name id of an attribute chain, e.g. ``subprocess`` in
    ``subprocess.run`` or ``requests`` in ``requests.sessions.post``."""
    cur = node
    while isinstance(cur, ast.Attribute):
        cur = cur.value
    return cur.id if isinstance(cur, ast.Name) else None


def _call_is_destructive(call: ast.Call) -> bool:
    func = call.func
    attr = func.attr if isinstance(func, ast.Attribute) else (
        func.id if isinstance(func, ast.Name) else None)
    root = _root_name(func)

    if attr in _DESTRUCTIVE_ATTRS:
        return True
    if attr in _SUBPROCESS_ATTRS and root in _SUBPROCESS_ROOTS:
        return True
    if attr == "delete" or (attr in _HTTP_ATTRS and root in _HTTP_ROOTS):
        return True
    # open(path, "w") / open(path, mode="a") — a file overwrite/append.
    if isinstance(func, ast.Name) and func.id == "open":
        mode = None
        if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
            mode = call.args[1].value
        for kw in call.keywords:
            if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                mode = kw.value.value
        if isinstance(mode, str) and mode.strip() in _WRITE_MODES:
            return True
    return False


def _body_is_destructive(func: ast.AST) -> bool:
    """True if the function body performs a destructive/irreversible operation."""
    for node in ast.walk(func):
        if isinstance(node, ast.Call) and _call_is_destructive(node):
            return True
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _DANGER_STR.search(node.value):
                return True
    return False


def _tool_is_destructive(func: ast.AST) -> bool:
    """A tool is destructive if its name carries a destructive verb OR its body
    performs a destructive op — unless it is a plainly read-only tool."""
    name = getattr(func, "name", "") or ""
    tokens = _name_tokens(name)
    destructive_name = bool(tokens & _DESTRUCTIVE_NAME_TOKENS)
    destructive_body = _body_is_destructive(func)
    readonly_name = bool(tokens & _READONLY_NAME_TOKENS) and not destructive_name
    # Read-only tools never fire, even if a helper call looks write-ish.
    if readonly_name and not destructive_body:
        return False
    return destructive_name or destructive_body


# ---------------------------------------------------------------------------
# Tool registration — is a function exposed to an agent as a tool?
# ---------------------------------------------------------------------------
# Decorator names (bare or dotted last attr) that register an agent tool.
_TOOL_DECORATORS = {"tool", "function_tool", "register_for_execution",
                    "register_for_llm", "agent_tool"}
# Constructor / factory names that wrap a plain function into a tool object.
_TOOL_WRAPPERS = {"Tool", "StructuredTool", "FunctionTool", "from_function",
                  "from_defaults"}
# Keyword args / variable names whose list value holds agent tools.
_TOOLS_KW = "tools"
_TOOLS_VARS = {"tools", "toolset", "agent_tools", "all_tools", "tool_list"}
# AutoGen-style registration helpers.
_REGISTER_CALLS = {"register_function", "register_tool"}


def _decorator_name(dec: ast.AST) -> Optional[str]:
    if isinstance(dec, ast.Call):
        dec = dec.func
    if isinstance(dec, ast.Name):
        return dec.id
    if isinstance(dec, ast.Attribute):
        return dec.attr
    return None


def _def_is_tool_decorated(func: ast.AST) -> bool:
    for dec in getattr(func, "decorator_list", []):
        if _decorator_name(dec) in _TOOL_DECORATORS:
            return True
    return False


def _collect_registered_names(tree: ast.Module) -> Set[str]:
    """Names of functions registered as agent tools via wrappers / lists /
    register_* calls (decorator-based registration is handled per-def)."""
    names: Set[str] = set()

    def add_names_in(node: Optional[ast.AST]) -> None:
        if node is None:
            return
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name):
                names.add(sub.id)

    for node in ast.walk(tree):
        # Tool(func=fn) / StructuredTool.from_function(fn) / FunctionTool.from_defaults(fn=fn)
        if isinstance(node, ast.Call):
            callee = None
            if isinstance(node.func, ast.Name):
                callee = node.func.id
            elif isinstance(node.func, ast.Attribute):
                callee = node.func.attr
            if callee in _TOOL_WRAPPERS or callee in _REGISTER_CALLS:
                for arg in node.args:
                    if isinstance(arg, ast.Name):
                        names.add(arg.id)
                for kw in node.keywords:
                    if kw.arg in {"func", "fn", "function", "coroutine"} and isinstance(kw.value, ast.Name):
                        names.add(kw.value.id)
            # tools=[a, b, c] passed to any call (agent/executor/create).
            for kw in node.keywords:
                if kw.arg == _TOOLS_KW and isinstance(kw.value, (ast.List, ast.Tuple, ast.Set)):
                    for elt in kw.value.elts:
                        add_names_in(elt)
        # tools = [a, b, c] variable assignment.
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id in _TOOLS_VARS:
                    if isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                        for elt in node.value.elts:
                            add_names_in(elt)
    return names


# ---------------------------------------------------------------------------
# Autonomous agent / executor construction
# ---------------------------------------------------------------------------
_EXECUTOR_CTORS = {
    # LangChain
    "AgentExecutor", "initialize_agent", "from_agent_and_tools",
    "create_react_agent", "create_tool_calling_agent",
    "create_openai_functions_agent", "create_openai_tools_agent",
    # CrewAI
    "Crew", "kickoff",
    # AutoGen
    "initiate_chat", "a_initiate_chat",
    # LlamaIndex
    "AgentRunner", "ReActAgent",
}
# Run methods that, when carrying a tools= kwarg, wire tools into an LLM run
# (OpenAI/Anthropic tool-calling loops, LangGraph, etc.).
_RUN_WITH_TOOLS_ATTRS = {"create", "run", "invoke", "stream", "complete",
                         "chat", "generate", "step"}


def _has_autonomous_executor(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = None
        if isinstance(node.func, ast.Name):
            callee = node.func.id
        elif isinstance(node.func, ast.Attribute):
            callee = node.func.attr
        if callee in _EXECUTOR_CTORS:
            return True
        # A run/create call that passes tools= is an autonomous tool-calling run.
        if callee in _RUN_WITH_TOOLS_ATTRS:
            if any(kw.arg == _TOOLS_KW for kw in node.keywords):
                return True
    return False


# ---------------------------------------------------------------------------
# Approval / confirmation / human-in-the-loop markers (file-scoped)
# ---------------------------------------------------------------------------
_APPROVAL_MARKERS = {
    "human_input", "require_approval", "requires_approval", "needs_approval",
    "interrupt", "interrupt_before", "interrupt_after", "confirm",
    "confirmation", "confirmed", "humanapproval", "human_approval",
    "human_in_the_loop", "humaninputrun", "human_tool", "dry_run", "dryrun",
    "allow_list", "allowlist", "allowed_tools", "approval", "approve",
    "ask_human", "get_approval", "await_approval", "checkpointer",
}


def _has_approval_marker(tree: ast.Module) -> bool:
    """True if any approval / confirmation / HITL marker appears in the file.

    ``human_input_mode`` is special: AutoGen's ``human_input_mode="NEVER"`` is
    precisely the *autonomous* setting, so it does NOT count as an approval
    gate; any other value does."""
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg:
            arg = node.arg.lower()
            if arg == "human_input_mode":
                if isinstance(node.value, ast.Constant) and \
                        isinstance(node.value.value, str) and \
                        node.value.value.strip().upper() == "NEVER":
                    continue  # explicitly no human — not a gate
                return True
            if arg in _APPROVAL_MARKERS:
                return True
        if isinstance(node, ast.Name) and node.id.lower() in _APPROVAL_MARKERS:
            return True
        if isinstance(node, ast.Attribute) and node.attr.lower() in _APPROVAL_MARKERS:
            return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name.lower() in _APPROVAL_MARKERS:
                return True
    return False


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------
def _make_hb001(func: ast.AST, filename: str) -> Finding:
    name = getattr(func, "name", "<tool>")
    reason = (
        f"the destructive tool '{name}' is exposed to an autonomous agent/"
        "executor with no human-approval, confirmation, or human-in-the-loop "
        "gate anywhere — the agent can invoke a delete/payment/send/deploy/"
        "shell action on its own, with no one able to stop it, and the effect "
        "is irreversible."
    )
    fix = (
        "Put a human in the loop before the destructive action: gate the tool "
        "behind an approval/confirmation step (LangGraph interrupt, an "
        "approval tool, AutoGen human_input_mode, a require_approval/dry_run "
        "flag, or an allow-list), or remove the destructive tool from the "
        "agent's autonomous tool set."
    )
    return Finding(
        file=filename, line=func.lineno, col=func.col_offset + 1,
        rule=HB001, severity=BLOCKER, message=reason, fix=fix,
    )


def _make_hb002(func: ast.AST, filename: str) -> Finding:
    name = getattr(func, "name", "<tool>")
    reason = (
        f"the destructive tool '{name}' is registered as an agent tool and an "
        "agent framework is present, but its wiring/approval state is uncertain "
        "(no agent/executor construction is visible in this file) — if it is "
        "handed to an autonomous agent without an approval gate, it can perform "
        "an irreversible action unattended."
    )
    fix = (
        "Confirm this tool is only reachable behind a human-approval / "
        "confirmation / human-in-the-loop step before an autonomous agent can "
        "call it; if it is intentionally gated elsewhere, suppress with "
        "'# handbrake: ignore'."
    )
    return Finding(
        file=filename, line=func.lineno, col=func.col_offset + 1,
        rule=HB002, severity=WARN, message=reason, fix=fix,
    )


# ---------------------------------------------------------------------------
# Suppression
# ---------------------------------------------------------------------------
def _line_suppresses(line: str, rule: str) -> bool:
    if INLINE_IGNORE in line:
        return True
    idx = line.find(NOQA)
    if idx == -1:
        return False
    rest = line[idx + len(NOQA):].lstrip()
    if not rest.startswith(":"):
        return True  # bare noqa suppresses everything on the line
    return rule in rest


def _apply_inline_ignore(findings: List[Finding], source: str) -> List[Finding]:
    lines = source.splitlines()
    kept: List[Finding] = []
    for f in findings:
        idx = f.line - 1
        if 0 <= idx < len(lines) and _line_suppresses(lines[idx], f.rule):
            continue
        kept.append(f)
    return kept


# ---------------------------------------------------------------------------
# Python analysis
# ---------------------------------------------------------------------------
def _iter_defs(tree: ast.Module):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _scan_python(source: str, filename: str) -> List[Finding]:
    tree = ast.parse(source, filename=filename)
    # Engage only when an agent framework is imported — otherwise stay quiet.
    if not _uses_agent_framework(tree):
        return []

    registered = _collect_registered_names(tree)
    has_executor = _has_autonomous_executor(tree)
    has_approval = _has_approval_marker(tree)

    findings: List[Finding] = []
    for func in _iter_defs(tree):
        is_registered = func.name in registered or _def_is_tool_decorated(func)
        if not is_registered:
            continue
        if not _tool_is_destructive(func):
            continue
        if has_approval:
            continue  # an approval/HITL marker short-circuits to clean
        if has_executor:
            findings.append(_make_hb001(func, filename))
        else:
            findings.append(_make_hb002(func, filename))

    # De-duplicate defensively by (line, col, rule).
    seen: Set[Tuple[int, int, str]] = set()
    unique: List[Finding] = []
    for f in findings:
        key = (f.line, f.col, f.rule)
        if key in seen:
            continue
        seen.add(key)
        unique.append(f)
    return _apply_inline_ignore(unique, source)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
PY_EXT = ".py"
CODE_EXTS = (PY_EXT,)


def scan_source(source: str, filename: str) -> List[Finding]:
    """Scan one source string. Only ``.py`` is analysed (AST-based).

    Raises SyntaxError only for unparseable Python; the CLI catches it."""
    ext = os.path.splitext(filename)[1].lower()
    if ext == PY_EXT:
        findings = _scan_python(source, filename)
    else:
        findings = []
    findings.sort(key=lambda f: (f.line, f.col, f.rule))
    return findings
