"""Data contracts that cross stage and agent boundaries."""

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Level = Literal["INFO", "WARN", "ERROR"]

# What the classifier may answer. Closed list for v1: the generator's fault types plus "unknown".
Category = Literal[
    "db_slowdown",
    "connection_pool_exhaustion",
    "cache_outage",
    "memory_leak",
    "bad_deploy",
    "queue_backlog",
    "cert_expiry",
    "disk_full",
    "unknown",
]
Severity = Literal["low", "medium", "high", "critical"]
# identified: evidence supports a root cause. tentative: weak evidence, the report says it is only guessing.
# insufficient_evidence: nothing credible, the report says so.
Status = Literal["identified", "tentative", "insufficient_evidence"]

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


# Everything below is written by an LLM, except TriageReport. extra="forbid" because Groq's strict structured-output
# mode needs `additionalProperties: false` on every object. These checks cover what one object can verify about itself;
# checks that need the log (do the cited lines exist?) live elsewhere.


class RootCauseCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    service: str
    confidence: float = Field(ge=0, le=1)
    evidence_lines: list[int]  # the service's own log lines that point at it; must belong to this service
    symptom_lines: list[int]  # lines from OTHER services showing the effect, e.g. a caller's "connection reset by X"

    @model_validator(mode="after")
    def _cites_something(self) -> Self:
        if not self.evidence_lines and not self.symptom_lines:
            raise ValueError(f"candidate '{self.service}' cites no lines at all")
        return self


class ClassifiedIncident(BaseModel):
    """The classifier's answer: what the issue is, not how it happened or how to fix it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Status
    severity: Severity  # always a best estimate: it comes from user impact, which is visible even if the cause is not
    category: Category
    root_cause_candidates: list[RootCauseCandidate] = Field(max_length=3)
    confidence: float = Field(ge=0, le=1)  # overall
    limitations: str  # what is missing, or what would make this certain
    summary: str

    @model_validator(mode="after")
    def _status_matches_candidates(self) -> Self:
        if self.status == "insufficient_evidence" and self.root_cause_candidates:
            raise ValueError("insufficient_evidence must have no root_cause_candidates")
        if self.status != "insufficient_evidence" and not self.root_cause_candidates:
            raise ValueError(f"{self.status} needs at least one root_cause_candidate")
        return self

    @model_validator(mode="after")
    def _candidates_are_distinct(self) -> Self:
        services = [c.service for c in self.root_cause_candidates]
        if len(set(services)) != len(services):
            raise ValueError(f"root_cause_candidates must be different services, got {services}")
        return self


class ChainLink(BaseModel):
    """One step of how the incident unfolded, tied to a log line."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    line_number: int
    service: str
    description: str


class NextStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["investigate", "remediate"]
    action: str
    rationale: str
    addresses: int | None  # 1-based position in how_it_happened that this step deals with; None if it addresses none
    check_first: str  # what to look at before acting


class FixPlan(BaseModel):
    """The fix suggestor's answer: how it happened, then what to do, each step tied back to the chain."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    how_it_happened: list[ChainLink]  # ordered; may be empty when the cause is unknown
    next_steps: list[NextStep] = Field(min_length=1)

    @model_validator(mode="after")
    def _steps_point_at_the_chain(self) -> Self:
        for step in self.next_steps:
            if step.addresses is not None and not 1 <= step.addresses <= len(self.how_it_happened):
                raise ValueError(
                    f"next step '{step.action}' addresses link {step.addresses}, "
                    f"but how_it_happened has {len(self.how_it_happened)} links"
                )
            if step.kind == "remediate" and step.addresses is None:
                raise ValueError(f"remediate step '{step.action}' must address a link in how_it_happened")
        return self


class TriageReport(BaseModel):
    """The final report. Built by plain Python from the two agent outputs, so caveats and model_id are not model-writable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    incident: ClassifiedIncident
    plan: FixPlan
    caveats: list[str]  # e.g. how many lines could not be parsed
    model_id: str

    @model_validator(mode="after")
    def _guess_gets_no_remedy(self) -> Self:
        if self.incident.status != "identified" and any(s.kind == "remediate" for s in self.plan.next_steps):
            raise ValueError(f"{self.incident.status} incidents may only have investigate steps")
        return self


class ParseSummary(BaseModel):
    """Compact view of a ParseResult, small enough to hand to an LLM (the full event list is not)."""

    total_lines: int
    parsed: int
    first_timestamp: datetime | None
    last_timestamp: datetime | None
    events_by_service: dict[str, dict[str, int]]  # service -> level -> count
    unparsed_by_reason: dict[str, int]
    unparsed_examples: list[UnparsedLine]  # first few, for illustration
