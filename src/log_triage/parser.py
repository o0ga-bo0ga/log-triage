"""Deterministic log parser. No LLM: format is `<ISO-8601 UTC timestamp> <service> <LEVEL> <message>`."""

import re
from collections import Counter, defaultdict
from datetime import datetime

from log_triage.schemas import (
    LogEvent,
    ParseResult,
    ParseSummary,
    UnparsedLine,
    UnparsedReason,
)

TIMESTAMP_SHAPE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
SERVICE_SHAPE = re.compile(r"^[a-z][a-z0-9-]*$")
LEVELS = ("INFO", "WARN", "ERROR")
UNPARSED_EXAMPLES = 5


def parse_line(line: str, line_number: int) -> LogEvent | UnparsedLine:
    def reject(reason: UnparsedReason) -> UnparsedLine:
        return UnparsedLine(line_number=line_number, raw=line, reason=reason)

    if not line.strip():
        return reject("empty")
    if line[0].isspace():
        return reject("continuation")

    parts = line.split(" ", 3)
    if len(parts) < 4 or not parts[3].strip():
        return reject("malformed")
    timestamp_text, service, level, message = parts
    if not TIMESTAMP_SHAPE.match(timestamp_text) or not SERVICE_SHAPE.match(service):
        return reject("malformed")

    try:
        timestamp = datetime.fromisoformat(timestamp_text)
    except ValueError:
        return reject("bad_timestamp")
    if level not in LEVELS:
        return reject("unknown_level")

    return LogEvent(
        line_number=line_number,
        timestamp=timestamp,
        service=service,
        level=level,
        message=message,
        raw=line,
    )


def parse_log(text: str) -> ParseResult:
    lines = text.split("\n")
    if lines and lines[-1] == "":  # the newline that ends the file is not a blank line
        lines.pop()

    events: list[LogEvent] = []
    unparsed: list[UnparsedLine] = []
    for line_number, line in enumerate(lines, start=1):
        parsed = parse_line(line.rstrip("\r"), line_number)
        if isinstance(parsed, LogEvent):
            events.append(parsed)
        else:
            unparsed.append(parsed)
    return ParseResult(events=events, unparsed=unparsed)


def summarize(result: ParseResult) -> ParseSummary:
    by_service: dict[str, Counter[str]] = defaultdict(Counter)
    for event in result.events:
        by_service[event.service][event.level] += 1
    timestamps = [e.timestamp for e in result.events]
    return ParseSummary(
        total_lines=len(result.events) + len(result.unparsed),
        parsed=len(result.events),
        first_timestamp=min(timestamps, default=None),
        last_timestamp=max(timestamps, default=None),
        events_by_service={s: dict(c) for s, c in sorted(by_service.items())},
        unparsed_by_reason=dict(Counter(u.reason for u in result.unparsed)),
        unparsed_examples=result.unparsed[:UNPARSED_EXAMPLES],
    )
