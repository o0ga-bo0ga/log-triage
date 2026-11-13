"""Offline tests for the fix suggestor's deterministic parts. The LLM's behaviour is measured by evals, not here."""

import pytest
from crewai import TaskOutput

from log_triage.fix_suggestor import MAX_RETRIES, build_crew, plan_guardrail
from log_triage.parser import parse_log
from log_triage.schemas import ClassifiedIncident, FixPlan

EVENTS = parse_log(
    "2026-01-15T14:00:00.000Z main-db WARN slow query\n2026-01-15T14:00:01.000Z api ERROR upstream timeout\n"
).events


def incident(status: str = "identified") -> ClassifiedIncident:
    candidates = [] if status == "insufficient_evidence" else [
        {"service": "main-db", "confidence": 0.8, "evidence_lines": [1], "symptom_lines": [2]}
    ]
    return ClassifiedIncident(
        status=status,
        severity="high",
        category="db_slowdown",
        root_cause_candidates=candidates,
        confidence=0.8,
        limitations="none",
        summary="main-db is slow",
    )


def plan(kind: str = "remediate", addresses: list[int] | None = None, chain: list[tuple[int, str]] | None = None) -> str:
    links = chain if chain is not None else [(1, "main-db"), (2, "api")]
    return FixPlan(
        how_it_happened=[{"line_number": n, "service": s, "description": "d"} for n, s in links],
        next_steps=[{"kind": kind, "action": "a", "rationale": "r", "addresses": [1] if addresses is None else addresses, "check_first": "c"}],
    ).model_dump_json()


def run(raw: str, status: str = "identified") -> tuple[bool, object]:
    return plan_guardrail(incident(status), EVENTS)(TaskOutput(description="d", agent="a", raw=raw))


def test_a_correct_plan_passes_as_json_text() -> None:
    ok, value = run(plan())
    assert ok and isinstance(value, str)


@pytest.mark.parametrize("status", ["tentative", "insufficient_evidence"])
def test_a_guess_gets_no_remedy(status: str) -> None:
    ok, message = run(plan("remediate", [1]), status)
    assert not ok and "only have investigate steps" in message
    assert run(plan("investigate", []), status)[0]


def test_a_chain_link_with_a_wrong_line_fails_with_its_position() -> None:
    ok, message = run(plan(chain=[(1, "main-db"), (1, "api")]))
    assert not ok and "how_it_happened[2]: line 1 belongs to 'main-db', not 'api'" in message


def test_a_step_addressing_a_missing_link_fails() -> None:
    ok, message = run('{"how_it_happened": [], "next_steps": [{"kind": "investigate", "action": "a", '
                      '"rationale": "r", "addresses": [3], "check_first": "c"}]}')
    assert not ok and "addresses link 3" in message


def test_the_task_is_wired_with_the_guardrail_and_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    [task] = build_crew(incident(), EVENTS).tasks
    assert task.output_pydantic is FixPlan
    assert task.guardrail is not None and task.guardrail_max_retries == MAX_RETRIES
    assert "{incident}" in task.description and "{evidence}" in task.description
