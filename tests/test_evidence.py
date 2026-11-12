import pytest

from generator.generate import generate_scenario
from log_triage.digest import build_digest, render
from log_triage.evidence import MAX_EXTRA_SERVICES, build_evidence, select_services
from log_triage.parser import parse_log
from log_triage.schemas import ClassifiedIncident, Digest, LogEvent, ParseResult, RootCauseCandidate


def scenario(category: str = "db_slowdown", difficulty: str = "hard", seed: int = 1) -> tuple[ParseResult, Digest, str]:
    s = generate_scenario(category, difficulty, seed)
    result = parse_log("\n".join(s.lines) + "\n")
    return result, build_digest(result), s.labels.root_cause_service


def incident(*candidates: RootCauseCandidate) -> ClassifiedIncident:
    return ClassifiedIncident(
        status="identified" if candidates else "insufficient_evidence",
        severity="high",
        category="db_slowdown",
        root_cause_candidates=list(candidates),
        confidence=0.7,
        limitations="none",
        summary="s",
    )


def candidate_in(events: list[LogEvent], service: str) -> RootCauseCandidate:
    lines = [e.line_number for e in events if e.service == service and e.level != "INFO"][:2]
    return RootCauseCandidate(service=service, confidence=0.8, evidence_lines=lines, symptom_lines=[])


@pytest.mark.parametrize("difficulty", ["easy", "ambiguous", "hard"])
def test_the_candidate_is_always_in_the_pack_even_without_an_onset(difficulty: str) -> None:
    result, digest, root = scenario(difficulty=difficulty)
    pack = build_evidence(incident(candidate_in(result.events, root)), digest, result.events)
    candidates, _ = select_services(incident(candidate_in(result.events, root)), digest)
    assert [s.service for s in candidates] == [root]
    assert f"\n{root}  onset" in pack


def test_the_cited_lines_are_quoted_from_the_log() -> None:
    result, digest, root = scenario()
    c = candidate_in(result.events, root)
    pack = build_evidence(incident(c), digest, result.events)
    by_line = {e.line_number: e for e in result.events}
    for number in c.evidence_lines:
        assert f"line {number}: {by_line[number].raw}" in pack


def test_symptom_lines_are_quoted_and_labelled() -> None:
    result, digest, root = scenario()
    symptom = next(e for e in result.events if e.service != root and e.level == "ERROR")
    c = RootCauseCandidate(service=root, confidence=0.8, evidence_lines=[], symptom_lines=[symptom.line_number])
    pack = build_evidence(incident(c), digest, result.events)
    assert f"symptom line {symptom.line_number}: {symptom.raw}" in pack


def test_extras_have_an_onset_are_capped_and_are_not_candidates() -> None:
    result, digest, root = scenario(difficulty="easy")
    candidates, extras = select_services(incident(candidate_in(result.events, root)), digest)
    assert 0 < len(extras) <= MAX_EXTRA_SERVICES
    assert all(s.onset is not None for s in extras)
    assert root not in [s.service for s in extras]
    assert [s.onset for s in extras] == sorted(s.onset for s in extras if s.onset)


def test_no_candidate_still_gets_the_services_with_bursts() -> None:
    result, digest, _ = scenario(difficulty="easy")
    candidates, extras = select_services(incident(), digest)
    assert candidates == [] and extras
    assert "named no root cause candidate" in build_evidence(incident(), digest, result.events)


def test_an_unknown_candidate_service_is_ignored_not_a_crash() -> None:
    result, digest, _ = scenario()
    ghost = RootCauseCandidate(service="payments", confidence=0.5, evidence_lines=[1], symptom_lines=[])
    candidates, _ = select_services(incident(ghost), digest)
    assert candidates == []
    build_evidence(incident(ghost), digest, result.events)


def test_every_service_is_either_shown_or_named_as_not_shown() -> None:
    result, digest, root = scenario()
    pack = build_evidence(incident(candidate_in(result.events, root)), digest, result.events)
    for s in digest.services:
        assert s.service in pack


def test_the_pack_is_smaller_than_the_full_digest() -> None:
    result, digest, root = scenario(difficulty="easy")
    pack = build_evidence(incident(candidate_in(result.events, root)), digest, result.events)
    assert len(pack) < len(render(digest))
