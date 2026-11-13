"""Offline tests for the classifier's deterministic parts. The LLM's behaviour is measured by evals, not here."""

import pytest
from crewai import TaskOutput

from log_triage.classifier import MAX_RETRIES, build_crew, incident_guardrail
from log_triage.parser import parse_log
from log_triage.schemas import ClassifiedIncident

EVENTS = parse_log(
    "2026-01-15T14:00:00.000Z main-db WARN slow query\n2026-01-15T14:00:01.000Z api ERROR upstream timeout\n"
).events


def answer(evidence: list[int], symptoms: list[int] | None = None) -> str:
    return ClassifiedIncident(
        status="identified",
        severity="high",
        category="db_slowdown",
        root_cause_candidates=[
            {"service": "main-db", "confidence": 0.8, "evidence_lines": evidence, "symptom_lines": symptoms or []}
        ],
        confidence=0.8,
        limitations="none",
        summary="main-db is slow",
    ).model_dump_json()


def run(raw: str) -> tuple[bool, object]:
    return incident_guardrail(EVENTS)(TaskOutput(description="d", agent="a", raw=raw))


def test_a_correct_answer_passes_as_json_text() -> None:
    ok, value = run(answer([1], [2]))
    assert ok and isinstance(value, str)  # a string, so crewai rebuilds .pydantic from it
    assert ClassifiedIncident.model_validate_json(value).root_cause_candidates[0].service == "main-db"


def test_json_wrapped_in_fences_and_prose_still_parses() -> None:
    ok, _ = run(f"Here is my answer:\n```json\n{answer([1])}\n```")
    assert ok


def test_a_bad_citation_fails_with_every_problem_listed() -> None:
    ok, message = run(answer([2, 999]))
    assert not ok
    assert "line 2 belongs to 'api'" in message and "line 999 is not a parsed log event" in message


@pytest.mark.parametrize("raw", ["I think it is the database.", '{"status": "identified"}'])
def test_a_non_answer_or_wrong_shape_fails(raw: str) -> None:
    ok, message = run(raw)
    assert not ok and "not a valid ClassifiedIncident" in message


def test_the_task_is_wired_with_the_guardrail_and_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    [task] = build_crew(EVENTS).tasks
    assert task.output_pydantic is ClassifiedIncident
    assert task.guardrail is not None and task.guardrail_max_retries == MAX_RETRIES
    assert "{digest}" in task.description  # filled in at kickoff
