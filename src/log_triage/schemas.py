"""Data contracts that cross stage and agent boundaries."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

Level = Literal["INFO", "WARN", "ERROR"]

# Why a line could not become a LogEvent:
#   empty          blank line
#   continuation   starts with whitespace, e.g. a stack-trace frame
#   malformed      wrong shape: too few fields, bad service name, not a timestamp, JSON, truncated
#   bad_timestamp  looks like a timestamp but is not a real date/time
#   unknown_level  level is not INFO, WARN or ERROR
UnparsedReason = Literal["empty", "continuation", "malformed", "bad_timestamp", "unknown_level"]


class LogEvent(BaseModel):
    """One successfully parsed log line."""

    model_config = ConfigDict(frozen=True)

    line_number: int  # 1-based, so the report can point at evidence
    timestamp: datetime  # timezone-aware (UTC)
    service: str
    level: Level
    message: str  # only the free-text part after the level
    raw: str  # the whole original line, unchanged


class UnparsedLine(BaseModel):
    """A line the parser rejected. Kept, never silently dropped."""

    model_config = ConfigDict(frozen=True)

    line_number: int
    raw: str
    reason: UnparsedReason


class ParseResult(BaseModel):
    events: list[LogEvent]
    unparsed: list[UnparsedLine]


class MessagePattern(BaseModel):
    """Many similar log messages grouped into one: numbers replaced by <n>, e.g. 'query timed out after <n>ms'."""

    model_config = ConfigDict(frozen=True)

    level: Level
    template: str
    count: int
    first_seen: datetime
    last_seen: datetime
    novel: bool  # first seen after the window's quiet start, so it looks new rather than background noise
    example: LogEvent  # first occurrence; its line_number is what a report can cite


class ServiceDigest(BaseModel):
    model_config = ConfigDict(frozen=True)

    service: str
    counts: dict[str, int]  # level -> number of lines
    onset: datetime | None  # first burst of WARN/ERROR lines, None if the service never had one
    patterns: list[MessagePattern]  # the most relevant few
    hidden_patterns: int  # how many more patterns exist but are not shown


class Digest(BaseModel):
    """A small, deterministic summary of a parsed log, meant for an LLM to read instead of every line."""

    window_start: datetime | None
    window_end: datetime | None
    total_lines: int
    parsed: int
    unparsed_by_reason: dict[str, int]
    services: list[ServiceDigest]  # earliest onset first, services without an onset last


class ParseSummary(BaseModel):
    """Compact view of a ParseResult, small enough to hand to an LLM (the full event list is not)."""

    total_lines: int
    parsed: int
    first_timestamp: datetime | None
    last_timestamp: datetime | None
    events_by_service: dict[str, dict[str, int]]  # service -> level -> count
    unparsed_by_reason: dict[str, int]
    unparsed_examples: list[UnparsedLine]  # first few, for illustration
