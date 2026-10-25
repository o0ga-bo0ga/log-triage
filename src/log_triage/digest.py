"""Deterministic digest: turns thousands of parsed log lines into a few pages an LLM can read. No LLM involved.

Assumption: the log window starts before the incident, so the first part of the window shows each service's
normal behaviour. Anything first seen after that quiet start is marked `novel`. If the window starts mid-incident
nothing is novel and patterns fall back to being ranked by severity and count.
"""

import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from log_triage.parser import parse_log
from log_triage.schemas import Digest, LogEvent, MessagePattern, ParseResult, ServiceDigest

ONSET_LINES = 5  # a service's onset = start of its first run of this many WARN/ERROR lines ...
ONSET_GAP_SECONDS = 10  # ... where each line is at most this many seconds after the previous one
QUIET_FRACTION = 0.25  # the first quarter of the window counts as "normal"
MAX_PATTERNS = 5  # patterns shown per service
LEVEL_ORDER = {"ERROR": 0, "WARN": 1, "INFO": 2}


def normalize(message: str) -> str:
    """Group messages that differ only in numbers: 'timed out after 120ms' -> 'timed out after <n>ms'."""
    return re.sub(r"\d+", "<n>", message)


def _onset(events: list[LogEvent]) -> datetime | None:
    """Start of the first sustained burst of WARN/ERROR lines (events must be sorted by time).

    A chain of close-together lines, not "N lines in a window": otherwise one stray background line shortly before
    a burst would be reported as the start of the burst.
    """
    run: list[datetime] = []
    for event in events:
        if event.level == "INFO":
            continue
        if run and (event.timestamp - run[-1]).total_seconds() > ONSET_GAP_SECONDS:
            run = []
        run.append(event.timestamp)
        if len(run) == ONSET_LINES:
            return run[0]
    return None


def _patterns(events: list[LogEvent], quiet_end: datetime) -> list[MessagePattern]:
    groups: dict[tuple[str, str], list[LogEvent]] = defaultdict(list)
    for event in events:
        groups[(event.level, normalize(event.message))].append(event)
    return [
        MessagePattern(
            level=level,
            template=template,
            count=len(group),
            first_seen=group[0].timestamp,
            last_seen=group[-1].timestamp,
            novel=group[0].timestamp > quiet_end,
            example=group[0],
        )
        for (level, template), group in groups.items()
    ]


def _service_digest(service: str, events: list[LogEvent], quiet_end: datetime) -> ServiceDigest:
    events = sorted(events, key=lambda e: e.timestamp)
    patterns = _patterns(events, quiet_end)
    # Novel first (a weak new signal must not lose to loud background noise), then errors before warnings
    # before info, then by how often it happened.
    patterns.sort(key=lambda p: (not p.novel, LEVEL_ORDER[p.level], -p.count, p.template))
    return ServiceDigest(
        service=service,
        counts=dict(Counter(e.level for e in events)),
        onset=_onset(events),
        patterns=patterns[:MAX_PATTERNS],
        hidden_patterns=max(0, len(patterns) - MAX_PATTERNS),
    )


def build_digest(result: ParseResult) -> Digest:
    unparsed_by_reason = dict(Counter(u.reason for u in result.unparsed))
    total_lines = len(result.events) + len(result.unparsed)
    if not result.events:
        return Digest(
            window_start=None,
            window_end=None,
            total_lines=total_lines,
            parsed=0,
            unparsed_by_reason=unparsed_by_reason,
            services=[],
        )

    start = min(e.timestamp for e in result.events)
    end = max(e.timestamp for e in result.events)
    quiet_end = start + (end - start) * QUIET_FRACTION

    by_service: dict[str, list[LogEvent]] = defaultdict(list)
    for event in result.events:
        by_service[event.service].append(event)
    services = [_service_digest(name, events, quiet_end) for name, events in by_service.items()]
    services.sort(key=lambda s: (s.onset is None, s.onset or start, s.service))

    return Digest(
        window_start=start,
        window_end=end,
        total_lines=total_lines,
        parsed=len(result.events),
        unparsed_by_reason=unparsed_by_reason,
        services=services,
    )


def render(digest: Digest) -> str:
    """The digest as plain text, the form an LLM (or a person reviewing it) reads."""
    if digest.window_start is None or digest.window_end is None:
        return f"No parsable log lines ({digest.total_lines} lines total)."

    def clock(ts: datetime) -> str:
        return ts.strftime("%H:%M:%S")

    unparsed = sum(digest.unparsed_by_reason.values())
    reasons = ", ".join(f"{reason} {n}" for reason, n in sorted(digest.unparsed_by_reason.items()))
    lines = [
        f"Window: {digest.window_start:%Y-%m-%d} {clock(digest.window_start)} to {clock(digest.window_end)} UTC. "
        f"{digest.parsed} lines parsed, {unparsed} could not be parsed" + (f" ({reasons})." if reasons else "."),
        f"Services ordered by onset = start of the first sustained burst ({ONSET_LINES}+ WARN/ERROR lines, each "
        f"within {ONSET_GAP_SECONDS}s of the last). onset none means no sustained burst, not that the service is "
        "healthy: check its NEW patterns.",
        "NEW = pattern first seen after the quiet start of the window.",
    ]
    for s in digest.services:
        onset = clock(s.onset) if s.onset else "none"
        counts = "  ".join(f"{level} {s.counts.get(level, 0)}" for level in LEVEL_ORDER)
        lines += ["", f"{s.service}  onset {onset}  {counts}"]
        for p in s.patterns:
            new = " NEW" if p.novel else ""
            lines.append(f"  {p.level} x{p.count} {clock(p.first_seen)}-{clock(p.last_seen)}{new}: {p.template}")
            lines.append(f"    e.g. line {p.example.line_number}: {p.example.raw}")
        if s.hidden_patterns:
            lines.append(f"  (+{s.hidden_patterns} more patterns not shown)")
    return "\n".join(lines)


if __name__ == "__main__":
    # Review a digest by eye: python -m log_triage.digest data/sample_logs/<scenario>.log
    print(render(build_digest(parse_log(Path(sys.argv[1]).read_text()))))
