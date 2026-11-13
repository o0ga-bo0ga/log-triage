import json
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from generator.faults import FAULTS
from log_triage.schemas import (
    Category,
    ChainLink,
    ClassifiedIncident,
    FixPlan,
    NextStep,
    RootCauseCandidate,
    TriageReport,
)


def candidate(service: str = "main-db", confidence: float = 0.8) -> RootCauseCandidate:
    return RootCauseCandidate(service=service, confidence=confidence, evidence_lines=[10, 12], symptom_lines=[])


def incident(status: str = "identified", candidates: list[RootCauseCandidate] | None = None) -> ClassifiedIncident:
    if candidates is None:
        candidates = [] if status == "insufficient_evidence" else [candidate()]
    return ClassifiedIncident(
        status=status,
        severity="high",
        category="db_slowdown",
        root_cause_candidates=candidates,
        confidence=0.7,
        limitations="none",
        summary="main-db is slow",
    )


def link(n: int = 1) -> ChainLink:
    return ChainLink(line_number=n, service="main-db", description=f"event {n}")


def step(kind: str = "investigate", addresses: list[int] | None = None) -> NextStep:
    return NextStep(kind=kind, action="look", rationale="why", addresses=addresses or [], check_first="logs")


def plan(chain_length: int = 2, *steps: NextStep) -> FixPlan:
    return FixPlan(how_it_happened=[link(i + 1) for i in range(chain_length)], next_steps=list(steps) or [step()])


def report(status: str, *steps: NextStep) -> TriageReport:
    return TriageReport(incident=incident(status), plan=plan(2, *steps), caveats=[], model_id="m")


# ClassifiedIncident


@pytest.mark.parametrize("status", ["identified", "tentative", "insufficient_evidence"])
def test_each_status_is_valid_with_the_right_candidates(status: str) -> None:
    assert incident(status).status == status


@pytest.mark.parametrize("status", ["identified", "tentative"])
def test_a_claimed_cause_needs_a_candidate(status: str) -> None:
    with pytest.raises(ValidationError, match="needs at least one"):
        incident(status, candidates=[])


def test_insufficient_evidence_must_not_name_a_candidate() -> None:
    with pytest.raises(ValidationError, match="no root_cause_candidates"):
        incident("insufficient_evidence", candidates=[candidate()])


def test_at_most_three_candidates() -> None:
    incident(candidates=[candidate(f"s{i}") for i in range(3)])
    with pytest.raises(ValidationError):
        incident(candidates=[candidate(f"s{i}") for i in range(4)])


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_confidence_is_between_zero_and_one(bad: float) -> None:
    with pytest.raises(ValidationError):
        candidate(confidence=bad)


def test_a_candidate_must_cite_at_least_one_line() -> None:
    with pytest.raises(ValidationError, match="cites no lines"):
        RootCauseCandidate(service="main-db", confidence=0.5, evidence_lines=[], symptom_lines=[])


def test_a_silent_service_may_be_backed_by_symptom_lines_alone() -> None:
    c = RootCauseCandidate(service="redis-cache", confidence=0.5, evidence_lines=[], symptom_lines=[40])
    assert c.symptom_lines == [40]


def test_candidates_must_be_different_services() -> None:
    with pytest.raises(ValidationError, match="different services"):
        incident(candidates=[candidate("main-db", 0.9), candidate("main-db", 0.5)])


def test_unknown_category_or_extra_field_is_rejected() -> None:
    data = incident().model_dump()
    with pytest.raises(ValidationError):
        ClassifiedIncident.model_validate({**data, "category": "gremlins"})
    with pytest.raises(ValidationError):
        ClassifiedIncident.model_validate({**data, "mood": "worried"})


def test_categories_match_the_generator_fault_types() -> None:
    assert set(get_args(Category)) == set(FAULTS) | {"unknown"}


# FixPlan


def test_remediate_step_must_address_a_link() -> None:
    with pytest.raises(ValidationError, match="must address"):
        plan(2, step("remediate", addresses=[]))
    assert plan(2, step("remediate", addresses=[2])).next_steps[0].addresses == [2]


def test_a_step_may_address_several_links() -> None:
    assert plan(3, step("remediate", addresses=[2, 3])).next_steps[0].addresses == [2, 3]


def test_investigate_step_may_address_nothing() -> None:
    assert plan(0, step("investigate", addresses=[])).how_it_happened == []


@pytest.mark.parametrize("addresses", [0, 3, -1])
def test_addresses_must_be_a_real_link(addresses: int) -> None:
    with pytest.raises(ValidationError, match="addresses link"):
        plan(2, step("investigate", addresses=[1, addresses]))


def test_a_plan_needs_at_least_one_step() -> None:
    with pytest.raises(ValidationError):
        FixPlan(how_it_happened=[], next_steps=[])


# TriageReport


def test_identified_incident_may_have_a_remedy() -> None:
    assert report("identified", step("remediate", addresses=[1])).incident.status == "identified"


@pytest.mark.parametrize("status", ["tentative", "insufficient_evidence"])
def test_a_guess_gets_no_remedy(status: str) -> None:
    with pytest.raises(ValidationError, match="only have investigate"):
        report(status, step("remediate", addresses=[1]))
    assert report(status, step("investigate")).incident.status == status


# Groq strict mode needs `additionalProperties: false` on every object (found by the structured-output probe).


def _objects(schema: Any) -> list[dict[str, Any]]:
    if isinstance(schema, dict):
        found = [schema] if schema.get("type") == "object" else []
        return found + [o for v in schema.values() for o in _objects(v)]
    if isinstance(schema, list):
        return [o for v in schema for o in _objects(v)]
    return []


@pytest.mark.parametrize("model", [ClassifiedIncident, FixPlan])
def test_agent_schemas_forbid_extra_properties_everywhere(model: type) -> None:
    objects = _objects(model.model_json_schema())
    assert len(objects) > 1  # the nested models are included
    assert all(o.get("additionalProperties") is False for o in objects)


@pytest.mark.parametrize("model", [ClassifiedIncident, FixPlan])
def test_agent_schemas_have_no_nullable_fields(model: type) -> None:
    # crewai strips null from the strict schema it sends the provider, so a nullable field could never be null
    # (found when Groq rejected a FixPlan with `addresses: int | None`). Use an empty list instead.
    assert '"null"' not in json.dumps(model.model_json_schema())
