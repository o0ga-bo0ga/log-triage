"""Offline tests for the Flow's wiring: the two agents are replaced by fakes, so routing and report assembly are
checked without an LLM."""

import pytest

from log_triage import flow
from log_triage.classifier import ClassifyResult
from log_triage.fix_suggestor import SuggestResult
from log_triage.schemas import ClassifiedIncident, FixPlan

# Line 3 is unparseable on purpose, to show up as a caveat. main-db's line 4 is logged after api's line 2.
LOG = """\
2026-01-15T14:00:00.000Z main-db WARN slow query
2026-01-15T14:00:01.000Z api ERROR upstream timeout
    at com.shop.Handler.handle(Handler.java:12)
2026-01-15T14:00:02.000Z main-db WARN lock wait exceeded
"""

INCIDENT = ClassifiedIncident(
    status="identified",
    severity="high",
    category="db_slowdown",
    root_cause_candidates=[{"service": "main-db", "confidence": 0.8, "evidence_lines": [1], "symptom_lines": [2]}],
    confidence=0.8,
    limitations="none",
    summary="main-db is slow",
)


def plan(*links: tuple[int, str]) -> FixPlan:
    return FixPlan(
        how_it_happened=[{"line_number": n, "service": s, "description": "d"} for n, s in links],
        next_steps=[{"kind": "remediate", "action": "a", "rationale": "r", "addresses": [1], "check_first": "c"}],
    )


@pytest.fixture
def agents(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Fake agents. Tests set what they return; `calls` records whether suggest ran."""
    fake: dict[str, object] = {
        "classified": ClassifyResult(incident=INCIDENT, error=None, model_id="m", total_tokens=10, attempts=1),
        "suggested": SuggestResult(plan=plan((1, "main-db"), (2, "api")), error=None, model_id="m", total_tokens=10, attempts=1),
        "calls": [],
    }
    monkeypatch.setattr(flow, "classify", lambda parsed: fake["classified"])

    def fake_suggest(incident: ClassifiedIncident, parsed: object) -> SuggestResult:
        fake["calls"].append("suggest")  # type: ignore[union-attr]
        return fake["suggested"]  # type: ignore[return-value]

    monkeypatch.setattr(flow, "suggest", fake_suggest)
    return fake


def test_a_classified_incident_becomes_a_full_report(agents: dict[str, object]) -> None:
    report, state = flow.triage(LOG)
    assert report is not None and report is state.report
    assert report.incident == INCIDENT and report.plan is not None and report.model_id == "m"
    assert len(state.parsed.events) == 3 and len(state.parsed.unparsed) == 1


def test_unparsed_lines_are_a_caveat(agents: dict[str, object]) -> None:
    report, _ = flow.triage(LOG)
    assert any("1 of 4 log lines could not be parsed" in c and "continuation 1" in c for c in report.caveats)


def test_a_chain_against_log_time_is_a_caveat_not_a_failure(agents: dict[str, object]) -> None:
    agents["suggested"] = SuggestResult(plan=plan((4, "main-db"), (2, "api")), error=None, model_id="m", total_tokens=10, attempts=1)
    report, _ = flow.triage(LOG)
    assert report is not None
    assert any(c.startswith("Causal order differs from log time at how_it_happened[2]") for c in report.caveats)


def test_retries_are_a_caveat(agents: dict[str, object]) -> None:
    agents["classified"] = ClassifyResult(incident=INCIDENT, error=None, model_id="m", total_tokens=10, attempts=3)
    report, _ = flow.triage(LOG)
    assert any("needed 3 attempts" in c for c in report.caveats)


def test_no_diagnosis_means_no_report_and_no_fix_suggestion(agents: dict[str, object]) -> None:
    agents["classified"] = ClassifyResult(incident=None, error="gave up", model_id="m", total_tokens=None, attempts=3)
    report, state = flow.triage(LOG)
    assert report is None and state.report is None
    assert state.classified.error == "gave up"
    assert agents["calls"] == []  # the router never sent it to the fix suggestor


def test_a_failed_fix_plan_still_reports_the_diagnosis(agents: dict[str, object]) -> None:
    agents["suggested"] = SuggestResult(plan=None, error="json_validate_failed", model_id="m", total_tokens=None, attempts=3)
    report, _ = flow.triage(LOG)
    assert report is not None and report.plan is None and report.incident == INCIDENT
    assert any(c.startswith("No fix plan: the fix suggestor failed after 3 attempts") for c in report.caveats)


def test_router_labels_are_not_method_names() -> None:
    # crewai treats labels and method names as one namespace: a clash loops forever or refuses to start
    assert not {"classified", "unclassified"} & set(dir(flow.TriageFlow))
