from datetime import datetime, timedelta, timezone

import pytest

from generator.faults import FAULTS
from generator.generate import PROFILES, generate_scenario
from log_triage.digest import MAX_PATTERNS, build_digest, normalize, render
from log_triage.parser import parse_log
from log_triage.schemas import Digest

BASE = datetime(2026, 1, 15, 14, 0, 0, tzinfo=timezone.utc)


def digest_of(*rows: tuple[int, str, str, str]) -> Digest:
    """Build a digest from (seconds after 14:00:00, service, level, message) rows."""
    lines = [
        f"{(BASE + timedelta(seconds=t)).isoformat(timespec='milliseconds').replace('+00:00', 'Z')} {s} {lvl} {msg}"
        for t, s, lvl, msg in rows
    ]
    return build_digest(parse_log("\n".join(lines) + "\n"))


def service(digest: Digest, name: str):
    return next(s for s in digest.services if s.service == name)


# A window of 1000s: the quiet start ends at 250s. These two rows pin the window for the small tests.
EDGES = [(0, "edge", "INFO", "start"), (1000, "edge", "INFO", "end")]


def test_normalize_replaces_numbers_only() -> None:
    assert normalize("query timed out after 18428ms calling main-db") == "query timed out after <n>ms calling main-db"
    assert normalize("tls: expired certificate from 10.0.5.7") == "tls: expired certificate from <n>.<n>.<n>.<n>"
    assert normalize("no digits here") == "no digits here"


def test_similar_messages_become_one_pattern_with_exact_stats() -> None:
    digest = digest_of(
        (10, "a", "WARN", "slow query 120ms"),
        (20, "a", "WARN", "slow query 95ms"),
        (30, "a", "WARN", "slow query 3000ms"),
        (40, "a", "WARN", "connection reset"),
        *EDGES,
    )
    warns = {p.template: p for p in service(digest, "a").patterns if p.level == "WARN"}
    slow = warns["slow query <n>ms"]
    assert slow.count == 3
    assert slow.first_seen == BASE + timedelta(seconds=10)
    assert slow.last_seen == BASE + timedelta(seconds=30)
    assert slow.example.raw.endswith("slow query 120ms")
    assert warns["connection reset"].count == 1


def test_same_message_at_different_levels_stays_separate() -> None:
    digest = digest_of((10, "a", "WARN", "disk 90"), (20, "a", "ERROR", "disk 95"), *EDGES)
    assert {(p.level, p.template) for p in service(digest, "a").patterns} == {
        ("WARN", "disk <n>"),
        ("ERROR", "disk <n>"),
    }


def test_onset_is_the_start_of_the_first_burst() -> None:
    burst = [(400 + i * 10, "burst", "ERROR", "boom") for i in range(5)]  # 5 errors within 40s
    too_few = [(400 + i * 10, "few", "ERROR", "boom") for i in range(4)]
    too_slow = [(i * 100, "slow", "ERROR", "boom") for i in range(1, 6)]  # 5 errors, 100s apart
    digest = digest_of(*burst, *too_few, *too_slow, *EDGES)

    assert service(digest, "burst").onset == BASE + timedelta(seconds=400)
    assert service(digest, "few").onset is None
    assert service(digest, "slow").onset is None


def test_a_stray_line_before_a_burst_is_not_the_onset() -> None:
    stray_then_burst = [(380, "a", "WARN", "stray"), *[(400 + i * 5, "a", "ERROR", "boom") for i in range(5)]]
    digest = digest_of(*stray_then_burst, *EDGES)
    assert service(digest, "a").onset == BASE + timedelta(seconds=400)  # not 380


def test_info_lines_never_count_towards_onset() -> None:
    digest = digest_of(*[(400 + i, "chatty", "INFO", "ok") for i in range(20)], *EDGES)
    assert service(digest, "chatty").onset is None


def test_services_are_ordered_by_onset_with_quiet_ones_last() -> None:
    late = [(500 + i, "late", "ERROR", "boom") for i in range(5)]
    early = [(300 + i, "early", "ERROR", "boom") for i in range(5)]
    digest = digest_of(*late, *early, (100, "quiet", "INFO", "ok"), *EDGES)
    assert [s.service for s in digest.services if s.service != "edge"] == ["early", "late", "quiet"]


def test_novel_means_first_seen_after_the_quiet_start() -> None:
    digest = digest_of(
        (0, "a", "WARN", "background ping"),
        (600, "a", "WARN", "background ping"),
        (600, "a", "ERROR", "disk failure"),
        *EDGES,
    )
    novelty = {p.template: p.novel for p in service(digest, "a").patterns}
    assert novelty == {"background ping": False, "disk failure": True}


def test_a_weak_new_signal_is_not_crowded_out_by_loud_background_noise() -> None:
    background = [
        (t, "svc", "ERROR", f"background task {name} failed")
        for name in ("alpha", "beta", "gamma", "delta", "epsilon", "zeta")
        for t in range(0, 200, 4)  # 50 lines each, all inside the quiet start
    ]
    digest = digest_of(*background, (600, "svc", "WARN", "lock contention detected"), *EDGES)

    shown = service(digest, "svc")
    assert shown.patterns[0].template == "lock contention detected"
    assert shown.patterns[0].novel
    assert len(shown.patterns) == MAX_PATTERNS
    assert shown.hidden_patterns == 2  # 7 patterns exist, 5 shown


def test_unparsed_lines_are_reported_not_hidden() -> None:
    text = f"{BASE.isoformat().replace('+00:00', 'Z')} a INFO ok\nthis is garbage\n"
    digest = build_digest(parse_log(text))
    assert digest.total_lines == 2
    assert digest.parsed == 1
    assert digest.unparsed_by_reason == {"malformed": 1}
    assert "1 could not be parsed (malformed 1)" in render(digest)


def test_empty_input() -> None:
    digest = build_digest(parse_log(""))
    assert digest.services == []
    assert render(digest) == "No parsable log lines (0 lines total)."


def test_render_shows_the_facts_a_reader_needs() -> None:
    digest = digest_of((600, "db", "ERROR", "deadlock detected between pid 12 and pid 34"), *EDGES)
    text = render(digest)
    assert "db  onset none  ERROR 1  WARN 0  INFO 0" in text
    assert "ERROR x1 14:10:00-14:10:00 NEW: deadlock detected between pid <n> and pid <n>" in text
    assert "e.g. line 1: 2026-01-15T14:10:00.000Z db ERROR deadlock detected between pid 12 and pid 34" in text


GRID = [(c, d, s) for c in FAULTS for d in PROFILES for s in (1, 2)]


@pytest.mark.parametrize(("category", "difficulty", "seed"), GRID)
def test_digest_of_generated_incident_is_consistent_and_keeps_the_root_cause_clue(
    category: str, difficulty: str, seed: int
) -> None:
    scenario = generate_scenario(category, difficulty, seed, noise=0.01)
    lines = scenario.lines
    digest = build_digest(parse_log("\n".join(lines) + "\n"))
    labels = scenario.labels

    # Nothing lost or invented in the counts.
    assert sum(sum(s.counts.values()) for s in digest.services) == digest.parsed
    assert digest.unparsed_by_reason == labels.expected_unparsed

    # Every cited line really is that line, from that service (so a report can cite it safely).
    for s in digest.services:
        for p in s.patterns:
            assert lines[p.example.line_number - 1] == p.example.raw
            assert p.example.service == s.service
            assert p.example.level == p.level

    # Small enough for an LLM.
    assert len(render(digest)) < 14000

    # The point of the digest: the root cause service's fault signal survives, shown and marked NEW.
    fault_start = datetime.fromisoformat(labels.fault_start)
    root = service(digest, labels.root_cause_service)
    assert any(p.novel and p.first_seen >= fault_start for p in root.patterns)
