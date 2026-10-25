import json
from collections import Counter
from pathlib import Path

import pytest

from generator.generate import generate_scenario
from log_triage.parser import parse_line, parse_log, summarize
from log_triage.schemas import LogEvent, UnparsedLine
from log_triage.tools.log_parser import ParseLogFileTool

GOOD = "2026-01-15T14:29:58.723Z orders-api ERROR database call to main-db exceeded deadline of 5000ms"


def test_parses_a_good_line_into_its_fields() -> None:
    event = parse_line(GOOD, 7)
    assert isinstance(event, LogEvent)
    assert event.line_number == 7
    assert event.timestamp.isoformat() == "2026-01-15T14:29:58.723000+00:00"
    assert event.service == "orders-api"
    assert event.level == "ERROR"
    assert event.message == "database call to main-db exceeded deadline of 5000ms"
    assert event.raw == GOOD


@pytest.mark.parametrize(
    ("line", "reason"),
    [
        ("", "empty"),
        ("   ", "empty"),
        ("    at com.shop.Handler.handle(Handler.java:42)", "continuation"),
        ("\tat Foo.bar(Foo.java:1)", "continuation"),
        ("2026-01-15T14:29", "malformed"),
        ("2026-01-15T14:29:58.723Z orders-api ERROR", "malformed"),
        ("2026-01-15T14:29:58.723Z orders-api ERROR   ", "malformed"),
        ('{"ts": "2026-01-15T14:29:58.723Z", "service": "orders-api", "level": "error"}', "malformed"),
        ("yesterday orders-api ERROR something broke", "malformed"),
        ("2026-01-15T14:29:58.723Z Orders_API ERROR something broke", "malformed"),
        ("2026-13-45T25:61:00.000Z orders-api INFO hello", "bad_timestamp"),
        ("2026-01-15T14:29:58.723Z orders-api WARNING slow", "unknown_level"),
        ("2026-01-15T14:29:58.723Z orders-api FATAL boom", "unknown_level"),
        ("2026-01-15T14:29:58.723Z orders-api error lowercase level", "unknown_level"),
    ],
)
def test_rejects_bad_lines_with_a_reason(line: str, reason: str) -> None:
    result = parse_line(line, 3)
    assert isinstance(result, UnparsedLine)
    assert result.reason == reason
    assert result.raw == line
    assert result.line_number == 3


def test_trailing_newline_is_not_a_blank_line_but_a_middle_blank_line_is() -> None:
    result = parse_log(f"{GOOD}\n\n{GOOD}\n")
    assert len(result.events) == 2
    assert [(u.line_number, u.reason) for u in result.unparsed] == [(2, "empty")]


def test_windows_line_endings_are_handled() -> None:
    result = parse_log(f"{GOOD}\r\n{GOOD}\r\n")
    assert len(result.events) == 2
    assert result.events[0].raw == GOOD


@pytest.mark.parametrize(("category", "difficulty"), [("db_slowdown", "hard"), ("cert_expiry", "easy")])
def test_clean_generated_log_parses_with_nothing_rejected(category: str, difficulty: str) -> None:
    scenario = generate_scenario(category, difficulty, 1)
    result = parse_log("\n".join(scenario.lines) + "\n")
    assert result.unparsed == []
    assert [e.raw for e in result.events] == scenario.lines
    for event, line in zip(result.events, scenario.lines, strict=True):
        _, service, level, _ = line.split(" ", 3)
        assert (event.service, event.level) == (service, level)


@pytest.mark.parametrize(
    ("category", "difficulty", "seed"),
    [("db_slowdown", "hard", 1), ("memory_leak", "ambiguous", 2), ("disk_full", "easy", 3)],
)
def test_noisy_log_recovers_exactly_the_clean_events_and_rejects_exactly_the_injected_lines(
    category: str, difficulty: str, seed: int
) -> None:
    clean = generate_scenario(category, difficulty, seed)
    noisy = generate_scenario(category, difficulty, seed, noise=0.02)
    result = parse_log("\n".join(noisy.lines) + "\n")

    assert noisy.labels.expected_unparsed, "noise should inject something"
    assert [e.raw for e in result.events] == clean.lines
    assert dict(Counter(u.reason for u in result.unparsed)) == noisy.labels.expected_unparsed
    assert noisy.labels.scenario_id.endswith("-noisy")


def test_noise_covers_every_rejection_reason() -> None:
    labels = generate_scenario("db_slowdown", "hard", 1, noise=0.02).labels
    assert set(labels.expected_unparsed) == {"continuation", "empty", "unknown_level", "bad_timestamp", "malformed"}


def test_summary_counts_and_examples() -> None:
    scenario = generate_scenario("db_slowdown", "hard", 1, noise=0.01)
    result = parse_log("\n".join(scenario.lines) + "\n")
    summary = summarize(result)

    assert summary.total_lines == len(scenario.lines)
    assert summary.parsed == len(result.events)
    assert sum(sum(levels.values()) for levels in summary.events_by_service.values()) == summary.parsed
    assert summary.unparsed_by_reason == scenario.labels.expected_unparsed
    assert 0 < len(summary.unparsed_examples) <= 5
    assert summary.first_timestamp is not None and summary.last_timestamp is not None
    assert summary.first_timestamp < summary.last_timestamp


def test_summary_of_empty_input() -> None:
    summary = summarize(parse_log(""))
    assert summary.total_lines == 0
    assert summary.first_timestamp is None


def test_tool_returns_a_small_json_summary(tmp_path: Path) -> None:
    scenario = generate_scenario("db_slowdown", "hard", 1, noise=0.01)
    (tmp_path / "incident.log").write_text("\n".join(scenario.lines) + "\n")

    output = ParseLogFileTool(log_dir=tmp_path).run(file_name="incident.log")

    data = json.loads(output)
    assert data["total_lines"] == len(scenario.lines)
    assert "main-db" in data["events_by_service"]
    assert len(output) < 5000  # thousands of lines in, a few KB out


def test_tool_refuses_paths_outside_the_log_directory(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (tmp_path / "secret.txt").write_text("do not read me")

    tool = ParseLogFileTool(log_dir=log_dir)
    for name in ("../secret.txt", str(tmp_path / "secret.txt"), "missing.log"):
        assert tool.run(file_name=name).startswith("Error:")
