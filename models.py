"""Data structures shared between the scanner, CLI, and renderer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

# Severity ordering — a blocker fails the gate; a warning is advisory.
BLOCKER = "blocker"
WARN = "warn"

# Rule identifiers. These are agent-safety rules, not generic style rules: an
# autonomous LLM agent wired to a DESTRUCTIVE or IRREVERSIBLE tool with no
# human-approval gate can delete data, move money, or message customers on its
# own, with no one in the loop to stop it.
HB001 = "HB001"  # destructive tool exposed to an autonomous agent, no approval gate (blocker)
HB002 = "HB002"  # destructive agent tool defined, wiring/approval uncertain (warning)

RULE_SEVERITY = {HB001: BLOCKER, HB002: WARN}


@dataclass
class Finding:
    """A single missing-human-approval issue found in a source file.

    handbrake never imports or runs the target code — findings are derived
    purely from the parsed AST, so scanning untrusted source is safe."""

    file: str
    line: int
    col: int
    rule: str  # one of HB001 / HB002
    severity: str  # BLOCKER | WARN
    message: str  # what was found
    fix: str  # concrete, actionable hint


@dataclass
class ScanResult:
    """The full result of scanning one or more files."""

    files_scanned: int = 0
    findings: List[Finding] = field(default_factory=list)

    @property
    def blockers(self) -> List[Finding]:
        return [f for f in self.findings if f.severity == BLOCKER]

    @property
    def warnings(self) -> List[Finding]:
        return [f for f in self.findings if f.severity == WARN]

    @property
    def has_findings(self) -> bool:
        return bool(self.findings)
