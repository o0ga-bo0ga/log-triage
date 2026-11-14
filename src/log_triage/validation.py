"""Checks on an agent's output that need the log itself. Plain Python, no LLM.

An agent's claims are never trusted: a cited line must be a real parsed event, and it must belong to the service the
agent says it does. Every check returns ALL the problems found (never stops at the first), so a retry can show the
model everything that was wrong and evals can count them.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from log_triage.schemas import ClassifiedIncident, FixPlan, LogEvent

# unknown_service: the service never appears in the log.
# unknown_line:    the line number is not a parsed event (it does not exist, or the parser rejected it).
# wrong_service:   the line exists but belongs to another service than the one claimed.
# out_of_order:    a causal-chain link happened before the link listed ahead of it.
ProblemKind = Literal["unknown_service", "unknown_line", "wrong_service", "out_of_order"]


class Problem(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: ProblemKind
    location: str  # where in the agent's output, e.g. "root_cause_candidates[1]"
    message: str  # written so it can be shown to the model on a retry


class _Facts:
    """What the log says, built once from the parsed events."""

    def __init__(self, events: list[LogEvent]) -> None:
        self.by_line = {e.line_number: e for e in events}
        self.services = {e.service for e in events}

    def check(self, location: str, service: str, line_number: int | None = None) -> list[Problem]:
        problems: list[Problem] = []
        if service not in self.services:
            problems.append(Problem(kind="unknown_service", location=location, message=f"service '{service}' does not appear in the log"))
        if line_number is not None:
            event = self.by_line.get(line_number)
            if event is None:
                problems.append(Problem(kind="unknown_line", location=location, message=f"line {line_number} is not a parsed log event"))
            elif event.service != service:
                problems.append(
                    Problem(
                        kind="wrong_service",
                        location=location,
                        message=f"line {line_number} belongs to '{event.service}', not '{service}'",
                    )
                )
        return problems


def check_incident(incident: ClassifiedIncident, events: list[LogEvent]) -> list[Problem]:
    """Every candidate service must exist, and every line it cites must be a real line from that service."""
    facts = _Facts(events)
    problems: list[Problem] = []
    for i, candidate in enumerate(incident.root_cause_candidates):
        location = f"root_cause_candidates[{i}]"
        problems += facts.check(location, candidate.service)
        for line_number in candidate.evidence_lines:  # the service's own lines: must exist and belong to it
            problems += [p for p in facts.check(location, candidate.service, line_number) if p.kind != "unknown_service"]
        for line_number in candidate.symptom_lines:  # lines from other services: only need to exist
            problems += [p for p in facts.check(location, candidate.service, line_number) if p.kind == "unknown_line"]
    return problems


def check_plan(plan: FixPlan, events: list[LogEvent]) -> list[Problem]:
    """Every link in the causal chain must be a real line from the service it names. Links are numbered from 1,
    the same numbering `addresses` uses."""
    facts = _Facts(events)
    problems: list[Problem] = []
    for position, link in enumerate(plan.how_it_happened, start=1):
        problems += facts.check(f"how_it_happened[{position}]", link.service, link.line_number)
    return problems


def check_chain_order(plan: FixPlan, events: list[LogEvent]) -> list[Problem]:
    """Links logged earlier than the link listed ahead of them. A WARNING for the report, never a reason to reject:
    logs record when something was noticed, not when it began, so a sound causal chain can run against log time
    (seen live: a memory leak's first heap warning was logged 8s after the gateway errors it caused)."""
    by_line = {e.line_number: e for e in events}
    warnings: list[Problem] = []
    previous: LogEvent | None = None
    for position, link in enumerate(plan.how_it_happened, start=1):
        event = by_line.get(link.line_number)
        if event is None:
            continue  # check_plan reports it; it has no timestamp to compare
        if previous is not None and event.timestamp < previous.timestamp:
            warnings.append(
                Problem(
                    kind="out_of_order",
                    location=f"how_it_happened[{position}]",
                    message=f"line {event.line_number} ({event.timestamp:%H:%M:%S}) was logged before the link listed "
                    f"ahead of it, line {previous.line_number} ({previous.timestamp:%H:%M:%S})",
                )
            )
        previous = event
    return warnings
