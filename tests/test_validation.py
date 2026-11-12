from log_triage.parser import parse_log
from log_triage.schemas import ChainLink, ClassifiedIncident, FixPlan, LogEvent, NextStep, RootCauseCandidate
from log_triage.validation import check_incident, check_plan

# Line 3 is blank, so the parser rejects it: the numbering has a gap a model could trip over.
LOG = """\
2026-01-15T14:00:00.000Z main-db INFO healthy
2026-01-15T14:00:01.000Z api ERROR upstream timeout

2026-01-15T14:00:02.000Z main-db WARN slow query
"""
EVENTS: list[LogEvent] = parse_log(LOG).events


def incident(*candidates: RootCauseCandidate) -> ClassifiedIncident:
    return ClassifiedIncident(
        status="identified",
        severity="high",
        category="db_slowdown",
        root_cause_candidates=list(candidates),
        confidence=0.8,
        limitations="none",
        summary="s",
    )


def candidate(service: str, *lines: int, symptoms: tuple[int, ...] = ()) -> RootCauseCandidate:
    return RootCauseCandidate(service=service, confidence=0.8, evidence_lines=list(lines), symptom_lines=list(symptoms))


def plan(*links: tuple[int, str]) -> FixPlan:
    chain = [ChainLink(line_number=n, service=s, description="d") for n, s in links]
    step = NextStep(kind="investigate", action="a", rationale="r", addresses=None, check_first="c")
    return FixPlan(how_it_happened=chain, next_steps=[step])


def test_a_correct_incident_has_no_problems() -> None:
    assert check_incident(incident(candidate("main-db", 1, 4), candidate("api", 2)), EVENTS) == []


def test_a_line_past_the_end_of_the_log_is_unknown() -> None:
    [problem] = check_incident(incident(candidate("main-db", 999)), EVENTS)
    assert problem.kind == "unknown_line"
    assert problem.location == "root_cause_candidates[0]"
    assert "999" in problem.message


def test_a_line_the_parser_rejected_is_unknown() -> None:
    [problem] = check_incident(incident(candidate("main-db", 3)), EVENTS)
    assert problem.kind == "unknown_line"


def test_a_line_from_another_service_is_wrong_service() -> None:
    [problem] = check_incident(incident(candidate("main-db", 2)), EVENTS)
    assert problem.kind == "wrong_service"
    assert "'api'" in problem.message and "'main-db'" in problem.message


def test_a_symptom_line_from_another_service_is_fine() -> None:
    assert check_incident(incident(candidate("main-db", 1, symptoms=(2,))), EVENTS) == []


def test_a_symptom_line_must_still_exist() -> None:
    [problem] = check_incident(incident(candidate("main-db", 1, symptoms=(3,))), EVENTS)  # line 3 was rejected
    assert problem.kind == "unknown_line"


def test_a_service_that_is_not_in_the_log_is_unknown() -> None:
    kinds = [p.kind for p in check_incident(incident(candidate("payments", 1)), EVENTS)]
    assert "unknown_service" in kinds


def test_every_problem_is_reported_not_just_the_first() -> None:
    problems = check_incident(incident(candidate("main-db", 999, 2), candidate("api", 4)), EVENTS)
    assert [(p.kind, p.location) for p in problems] == [
        ("unknown_line", "root_cause_candidates[0]"),
        ("wrong_service", "root_cause_candidates[0]"),
        ("wrong_service", "root_cause_candidates[1]"),
    ]


def test_incident_without_candidates_has_nothing_to_check() -> None:
    insufficient = ClassifiedIncident(
        status="insufficient_evidence",
        severity="low",
        category="unknown",
        root_cause_candidates=[],
        confidence=0.1,
        limitations="x",
        summary="s",
    )
    assert check_incident(insufficient, EVENTS) == []


def test_a_correct_plan_has_no_problems() -> None:
    assert check_plan(plan((1, "main-db"), (2, "api")), EVENTS) == []


def test_plan_problems_are_located_by_link_number_from_one() -> None:
    problems = check_plan(plan((1, "main-db"), (2, "main-db"), (999, "api")), EVENTS)
    assert [(p.kind, p.location) for p in problems] == [
        ("wrong_service", "how_it_happened[2]"),
        ("unknown_line", "how_it_happened[3]"),
    ]


def test_an_empty_chain_has_no_problems() -> None:
    assert check_plan(plan(), EVENTS) == []
