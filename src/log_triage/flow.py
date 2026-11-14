"""The triage pipeline as a CrewAI Flow: plain-Python steps and two agent crews, wired by events.

    parse → classify_incident → route ─ "classified"   → suggest_fix → assemble_report → TriageReport
                                      └─ "unclassified" → report_failure                 → None

kickoff() returns the TriageReport, or None when the classifier could not produce a valid answer. Everything else
(attempts, tokens, errors) stays on flow.state for whoever needs it, e.g. the eval runner.
"""

import sys
from collections import Counter
from pathlib import Path
from typing import Literal

from crewai.flow import Flow, listen, router, start
from dotenv import load_dotenv
from pydantic import BaseModel

from log_triage.classifier import ClassifyResult, classify
from log_triage.fix_suggestor import SuggestResult, suggest
from log_triage.parser import parse_log
from log_triage.schemas import ParseResult, TriageReport
from log_triage.validation import check_chain_order


class TriageState(BaseModel):
    """Everything one triage run produced. Every field has a default, as Flow state requires."""

    log_text: str = ""  # the only input
    parsed: ParseResult | None = None
    classified: ClassifyResult | None = None
    suggested: SuggestResult | None = None
    report: TriageReport | None = None


def caveats(state: TriageState) -> list[str]:
    """What the reader should know before trusting the report. Written by code, never by the model."""
    assert state.parsed is not None and state.classified is not None
    notes: list[str] = []
    unparsed = len(state.parsed.unparsed)
    if unparsed:
        total = unparsed + len(state.parsed.events)
        reasons = ", ".join(f"{r} {n}" for r, n in sorted(Counter(u.reason for u in state.parsed.unparsed).items()))
        notes.append(f"{unparsed} of {total} log lines could not be parsed and were not analysed ({reasons}).")
    if state.classified.attempts > 1:
        notes.append(f"The diagnosis needed {state.classified.attempts} attempts before it passed validation.")
    suggested = state.suggested
    if suggested is not None and suggested.plan is None:
        notes.append(f"No fix plan: the fix suggestor failed after {suggested.attempts} attempts ({suggested.error}).")
    elif suggested is not None and suggested.plan is not None:
        if suggested.attempts > 1:
            notes.append(f"The fix plan needed {suggested.attempts} attempts before it passed validation.")
        for warning in check_chain_order(suggested.plan, state.parsed.events):
            notes.append(f"Causal order differs from log time at {warning.location}: {warning.message}.")
    return notes


class TriageFlow(Flow[TriageState]):
    @start()
    def parse(self) -> None:
        self.state.parsed = parse_log(self.state.log_text)

    @listen(parse)
    def classify_incident(self) -> None:
        assert self.state.parsed is not None
        self.state.classified = classify(self.state.parsed)

    # Labels are events, not method names: a label equal to a method name makes crewai loop or refuse to start.
    @router(classify_incident)
    def route(self) -> Literal["classified", "unclassified"]:
        assert self.state.classified is not None
        return "classified" if self.state.classified.incident is not None else "unclassified"

    @listen("classified")
    def suggest_fix(self) -> None:
        assert self.state.parsed is not None and self.state.classified is not None
        assert self.state.classified.incident is not None
        self.state.suggested = suggest(self.state.classified.incident, self.state.parsed)

    @listen(suggest_fix)
    def assemble_report(self) -> TriageReport:
        assert self.state.classified is not None and self.state.classified.incident is not None
        assert self.state.suggested is not None
        self.state.report = TriageReport(
            incident=self.state.classified.incident,
            plan=self.state.suggested.plan,
            caveats=caveats(self.state),
            model_id=self.state.classified.model_id,
        )
        return self.state.report

    @listen("unclassified")
    def report_failure(self) -> None:
        return None  # the reason is on state.classified.error


def triage(log_text: str) -> tuple[TriageReport | None, TriageState]:
    """Run the whole pipeline on one log. Returns the report and the full state of the run."""
    flow = TriageFlow()
    report = flow.kickoff(inputs={"log_text": log_text})
    return report, flow.state


if __name__ == "__main__":
    # Triage one log: python -m log_triage.flow data/sample_logs/<scenario>.log [report.json]
    # CrewAI prints its progress panels to stdout, so give a path to get the report as a clean JSON file.
    load_dotenv()
    report, state = triage(Path(sys.argv[1]).read_text())
    if report is None:
        print(f"No report: {state.classified.error if state.classified else 'nothing ran'}", file=sys.stderr)
        sys.exit(1)
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(report.model_dump_json(indent=2) + "\n")
        print(f"Report written to {sys.argv[2]}")
    else:
        print(report.model_dump_json(indent=2))
