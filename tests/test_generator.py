import re
from collections import Counter
from datetime import datetime

import pytest

from generator.faults import FAULTS
from generator.generate import PROFILES, SEVERITY_THRESHOLDS, generate_scenario
from generator.topology import ENTRYPOINT

LINE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z [a-z-]+ (INFO|WARN|ERROR) .+$")

CASES = [(c, d, s) for c in FAULTS for d in PROFILES for s in (1, 2)]


def error_counts(lines: list[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for line in lines:
        _, service, level, _ = line.split(" ", 3)
        if level == "ERROR":
            counts[service] += 1
    return counts


@pytest.mark.parametrize(("category", "difficulty", "seed"), CASES)
def test_lines_are_well_formed_and_time_ordered(category: str, difficulty: str, seed: int) -> None:
    lines = generate_scenario(category, difficulty, seed).lines
    assert len(lines) > 2000
    assert all(LINE.match(line) for line in lines)
    timestamps = [line.split(" ", 1)[0] for line in lines]
    assert timestamps == sorted(timestamps)


@pytest.mark.parametrize(("category", "difficulty", "seed"), CASES)
def test_labels_are_consistent(category: str, difficulty: str, seed: int) -> None:
    labels = generate_scenario(category, difficulty, seed).labels
    assert labels.root_cause_service in FAULTS[category].origins
    assert labels.affected_services[0] == labels.root_cause_service
    assert (labels.decoy_service is not None) == PROFILES[difficulty].has_decoy
    if labels.decoy_service:
        assert labels.decoy_service not in labels.affected_services


@pytest.mark.parametrize(("category", "difficulty", "seed"), CASES)
def test_difficulty_controls_who_is_loudest(category: str, difficulty: str, seed: int) -> None:
    scenario = generate_scenario(category, difficulty, seed)
    origin = scenario.labels.root_cause_service
    ranked = error_counts(scenario.lines).most_common()

    if difficulty == "easy":
        assert ranked[0][0] == origin
    elif difficulty == "hard":
        assert ranked[0][0] != origin
        assert dict(ranked)[origin] < ranked[0][1] / 2  # origin only has baseline noise
    else:
        top_two = {ranked[0][0], ranked[1][0]}
        assert top_two == {origin, scenario.labels.decoy_service}


@pytest.mark.parametrize(("category", "difficulty", "seed"), CASES)
def test_severity_can_be_recomputed_from_the_log_alone(category: str, difficulty: str, seed: int) -> None:
    scenario = generate_scenario(category, difficulty, seed)
    labels = scenario.labels
    fault_start = datetime.fromisoformat(labels.fault_start)

    levels = []
    for line in scenario.lines:
        ts, service, level, _ = line.split(" ", 3)
        if service == ENTRYPOINT and datetime.fromisoformat(ts) >= fault_start:
            levels.append(level)
    errors = levels.count("ERROR")
    rate = round(errors / (errors + levels.count("INFO")), 3)

    assert rate == labels.user_error_rate
    expected = next((sev for threshold, sev in SEVERITY_THRESHOLDS if rate >= threshold), "low")
    assert labels.severity == expected


@pytest.mark.parametrize("difficulty", sorted(PROFILES))
def test_every_severity_occurs_within_each_difficulty(difficulty: str) -> None:
    severities = {
        generate_scenario(category, difficulty, seed).labels.severity
        for category in FAULTS
        for seed in range(1, 6)
    }
    assert severities == {"low", "medium", "high", "critical"}


def test_same_seed_is_identical_and_different_seed_differs() -> None:
    a = generate_scenario("db_slowdown", "hard", 1)
    b = generate_scenario("db_slowdown", "hard", 1)
    c = generate_scenario("db_slowdown", "hard", 2)
    assert a == b
    assert a.lines != c.lines
