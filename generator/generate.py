"""Synthetic multi-service log + label generator. Plain Python, no LLM, fully seeded.

One scenario = one log file + one labels file. Usage from the repo root:

    python -m generator.generate --category db_slowdown --difficulty hard --seed 1
    python -m generator.generate --all --seeds 3
"""

import argparse
import json
import random
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from generator.faults import DECOY_ERRORS, ENTRY_ERRORS, FAULTS, TRANSITIVE_ERRORS, Fault
from generator.topology import (
    BASE_ERRORS,
    BASE_WARNS,
    DEPENDENCIES,
    ENTRYPOINT,
    HEALTHY,
    callers_by_depth,
)

WINDOW_START = datetime(2026, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
WINDOW_MINUTES = 30
HOP_DELAY_SECONDS = 3  # each hop up the call chain notices the failure a little later
BASE_WARN_PER_MIN = 0.5
BASE_ERROR_PER_MIN = 0.1
PATHS = ("checkout", "cart", "orders", "products", "account")

# Target share of failing frontend requests, one per severity band. The scenario picks one, and every fault
# rate is scaled so the frontend lands near it. All rates scale together, so the loudness ordering (difficulty)
# is unchanged and severity does not depend on difficulty.
IMPACT_LEVELS = (0.05, 0.2, 0.4, 0.65)

# Severity rubric: share of frontend requests that fail after the fault starts.
# First threshold met wins; below all of them is "low".
SEVERITY_THRESHOLDS = ((0.50, "critical"), (0.30, "high"), (0.10, "medium"))


@dataclass(frozen=True)
class Profile:
    """How loud each part of the incident is, in ERROR lines per minute (WARN for origin_warn)."""

    origin_error_per_min: int
    origin_warn_per_min: int
    symptom_per_min: int  # per affected caller service
    has_decoy: bool


# easy: the origin is the loudest service.
# ambiguous: an unrelated decoy service is exactly as loud as the origin.
# hard: the origin only logs a few warnings; the loudest services are downstream symptoms.
PROFILES: dict[str, Profile] = {
    "easy": Profile(origin_error_per_min=60, origin_warn_per_min=3, symptom_per_min=20, has_decoy=False),
    "ambiguous": Profile(origin_error_per_min=30, origin_warn_per_min=3, symptom_per_min=12, has_decoy=True),
    "hard": Profile(origin_error_per_min=0, origin_warn_per_min=4, symptom_per_min=30, has_decoy=False),
}


@dataclass(frozen=True)
class Event:
    ts: datetime
    service: str
    level: str
    message: str

    def format(self) -> str:
        ts = self.ts.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        return f"{ts} {self.service} {self.level} {self.message}"


@dataclass(frozen=True)
class Labels:
    scenario_id: str
    seed: int
    category: str
    severity: str
    root_cause_service: str
    difficulty: str
    fault_start: str
    window_start: str
    window_end: str
    affected_services: list[str]  # origin first, then callers by distance from the origin
    decoy_service: str | None
    impact_scale: float
    user_error_rate: float  # failing share of frontend requests after fault_start; severity is derived from it
    noise: float  # extra bad lines inserted, as a fraction of the log's size (0 = clean)
    expected_unparsed: dict[str, int]  # parser rejection reason -> number of injected lines


@dataclass(frozen=True)
class Scenario:
    labels: Labels
    lines: list[str]


def _fields(rng: random.Random, origin: str = "", callee: str = "") -> dict[str, object]:
    return {
        "ms": rng.randint(5, 120),
        "fast": rng.randint(1, 15),
        "slow": rng.randint(1000, 30000),
        "id": rng.randint(10000, 99999),
        "n": rng.randint(1, 99),
        "pct": rng.randint(95, 99),
        "mem": rng.randint(1800, 2040),
        "path": rng.choice(PATHS),
        "ver": f"v2.{rng.randint(1, 30)}.{rng.randint(0, 9)}",
        "status": rng.choice((502, 503, 504)),
        "origin": origin,
        "callee": callee,
    }


def _ms(ts: datetime) -> datetime:
    """Truncate to milliseconds, the precision written to the log, so labels can be recomputed from the file."""
    return ts.replace(microsecond=ts.microsecond // 1000 * 1000)


def _severity(user_error_rate: float) -> str:
    for threshold, severity in SEVERITY_THRESHOLDS:
        if user_error_rate >= threshold:
            return severity
    return "low"


def _user_error_rate(events: list[Event], fault_start: datetime) -> float:
    """Failing share of frontend requests (ERROR / (ERROR + INFO)) from fault_start on."""
    levels = [e.level for e in events if e.service == ENTRYPOINT and e.ts >= fault_start]
    errors = levels.count("ERROR")
    return errors / (errors + levels.count("INFO"))


def _count(rng: random.Random, per_min: float, minutes: float) -> int:
    """Number of lines for a rate over a duration, with +-20% jitter."""
    mean = per_min * minutes
    return rng.randint(int(mean * 0.8), int(mean * 1.2))


def _emit(
    rng: random.Random,
    service: str,
    level: str,
    templates: tuple[str, ...],
    count: int,
    start: datetime,
    end: datetime,
    origin: str = "",
    callee: str = "",
) -> list[Event]:
    span = (end - start).total_seconds()
    return [
        Event(
            ts=_ms(start + timedelta(seconds=rng.uniform(0, span))),
            service=service,
            level=level,
            message=rng.choice(templates).format(**_fields(rng, origin, callee)),
        )
        for _ in range(count)
    ]


def _baseline(rng: random.Random, end: datetime) -> list[Event]:
    events: list[Event] = []
    for service, profile in HEALTHY.items():
        for level, templates, per_min in (
            ("INFO", profile.info, profile.info_per_min),
            ("WARN", BASE_WARNS, BASE_WARN_PER_MIN),
            ("ERROR", BASE_ERRORS, BASE_ERROR_PER_MIN),
        ):
            count = _count(rng, per_min, WINDOW_MINUTES)
            events += _emit(rng, service, level, templates, count, WINDOW_START, end)
    return events


def _fault_events(
    rng: random.Random,
    fault: Fault,
    profile: Profile,
    scale: float,
    origin: str,
    start: datetime,
    end: datetime,
) -> tuple[list[Event], list[str], int]:
    """Events caused by the fault. Returns (events, affected services origin-first, origin error count).

    `scale` multiplies all the profile's rates (see IMPACT_LEVELS).
    """
    minutes = (end - start).total_seconds() / 60
    events: list[Event] = []

    for level, template in fault.lead_in:
        events += _emit(rng, origin, level, (template,), 1, start, start + timedelta(seconds=2), origin)

    warn_count = _count(rng, profile.origin_warn_per_min * scale, minutes)
    events += _emit(rng, origin, "WARN", fault.origin_warn, warn_count, start, end, origin)
    error_count = _count(rng, profile.origin_error_per_min * scale, minutes)
    events += _emit(rng, origin, "ERROR", fault.origin_error, error_count, start, end, origin)

    affected = [origin]
    for depth, services in enumerate(callers_by_depth(origin), start=1):
        upstream = list(affected)  # only services from earlier levels can be a callee
        symptom_start = start + timedelta(seconds=depth * HOP_DELAY_SECONDS)
        symptom_minutes = (end - symptom_start).total_seconds() / 60
        for service in services:
            if depth == 1:
                templates = fault.caller_errors
            elif service == ENTRYPOINT:
                templates = ENTRY_ERRORS
            else:
                templates = TRANSITIVE_ERRORS
            callee = next(d for d in DEPENDENCIES[service] if d in upstream)
            count = _count(rng, profile.symptom_per_min * scale, symptom_minutes)
            events += _emit(rng, service, "ERROR", templates, count, symptom_start, end, origin, callee)
            affected.append(service)

    return events, affected, error_count


NOISE_KINDS = ("stack_trace", "empty", "unknown_level", "bad_timestamp", "json", "truncated")
UNKNOWN_LEVELS = ("WARNING", "FATAL", "DEBUG")


def _add_noise(lines: list[str], noise: float, scenario_id: str) -> tuple[list[str], dict[str, int]]:
    """Insert extra lines a correct parser must reject. Valid lines are never changed or removed, so the parsed
    events must equal the clean log's events. Returns (new lines, rejection reason -> count injected).

    Uses its own RNG, so the clean part of the scenario is identical with or without noise.
    """
    rng = random.Random(f"{scenario_id}-noise")
    error_indexes = [i for i, line in enumerate(lines) if line.split(" ", 3)[2] == "ERROR"]
    inserts: dict[int, list[str]] = {}  # insert after the line at this index
    expected: Counter[str] = Counter()

    for _ in range(round(len(lines) * noise)):
        kind = rng.choice(NOISE_KINDS)
        i = rng.choice(error_indexes) if kind == "stack_trace" else rng.randrange(len(lines))
        timestamp, service, _level, message = lines[i].split(" ", 3)

        if kind == "stack_trace":
            package = service.replace("-", "_")
            new = [
                f"    at com.shop.{package}.Handler.handle(Handler.java:{rng.randint(10, 400)})"
                for _ in range(rng.randint(2, 4))
            ]
            reason = "continuation"
        elif kind == "empty":
            new, reason = [""], "empty"
        elif kind == "unknown_level":
            new, reason = [f"{timestamp} {service} {rng.choice(UNKNOWN_LEVELS)} {message}"], "unknown_level"
        elif kind == "bad_timestamp":
            new, reason = [f"2026-13-45T25:61:00.000Z {service} INFO {message}"], "bad_timestamp"
        elif kind == "json":
            record = {"ts": timestamp, "service": service, "level": "error", "msg": message}
            new, reason = [json.dumps(record)], "malformed"
        else:  # truncated: cut inside the timestamp, as if the write was interrupted
            new, reason = [lines[i][: rng.randint(5, 23)]], "malformed"

        inserts.setdefault(i, []).extend(new)
        expected[reason] += len(new)

    noisy: list[str] = []
    for i, line in enumerate(lines):
        noisy.append(line)
        noisy.extend(inserts.get(i, []))
    return noisy, dict(expected)


def generate_scenario(category: str, difficulty: str, seed: int, noise: float = 0.0) -> Scenario:
    """Same arguments always yield identical logs and labels. noise > 0 adds unparseable lines (see _add_noise)."""
    fault = FAULTS[category]
    profile = PROFILES[difficulty]
    rng = random.Random(f"{category}-{difficulty}-{seed}")

    end = WINDOW_START + timedelta(minutes=WINDOW_MINUTES)
    fault_start = _ms(WINDOW_START + timedelta(minutes=WINDOW_MINUTES * rng.uniform(0.35, 0.65)))
    origin = rng.choice(fault.origins)
    target = rng.choice(IMPACT_LEVELS)
    # Frontend errors per minute that give `target` failures next to its healthy traffic, divided by the
    # profile's own frontend error rate = the multiplier for all rates.
    scale = target / (1 - target) * HEALTHY[ENTRYPOINT].info_per_min / profile.symptom_per_min

    events = _baseline(rng, end)
    fault_events, affected, origin_error_count = _fault_events(rng, fault, profile, scale, origin, fault_start, end)
    events += fault_events

    decoy = None
    if profile.has_decoy:
        decoy = rng.choice([s for s in DEPENDENCIES if s not in affected])
        # Same count as the origin's errors, so the two are exactly tied on loudness.
        events += _emit(rng, decoy, "ERROR", DECOY_ERRORS, origin_error_count, fault_start, end)

    events.sort(key=lambda e: (e.ts, e.service))
    user_error_rate = round(_user_error_rate(events, fault_start), 3)
    scenario_id = f"{category}-{difficulty}-s{seed}" + ("-noisy" if noise else "")
    lines = [e.format() for e in events]
    expected_unparsed: dict[str, int] = {}
    if noise:
        lines, expected_unparsed = _add_noise(lines, noise, scenario_id)
    labels = Labels(
        scenario_id=scenario_id,
        seed=seed,
        category=category,
        severity=_severity(user_error_rate),
        root_cause_service=origin,
        difficulty=difficulty,
        fault_start=fault_start.isoformat(timespec="milliseconds"),
        window_start=WINDOW_START.isoformat(),
        window_end=end.isoformat(),
        affected_services=affected,
        decoy_service=decoy,
        impact_scale=round(scale, 3),
        user_error_rate=user_error_rate,
        noise=noise,
        expected_unparsed=expected_unparsed,
    )
    return Scenario(labels=labels, lines=lines)


def write_scenario(scenario: Scenario, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    scenario_id = scenario.labels.scenario_id
    (out_dir / f"{scenario_id}.log").write_text("\n".join(scenario.lines) + "\n")
    (out_dir / f"{scenario_id}.labels.json").write_text(json.dumps(asdict(scenario.labels), indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic multi-service logs with labels.")
    parser.add_argument("--category", choices=sorted(FAULTS))
    parser.add_argument("--difficulty", choices=sorted(PROFILES))
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--all", action="store_true", help="every category x difficulty")
    parser.add_argument("--seeds", type=int, default=1, help="with --all: seeds 1..N per combination")
    parser.add_argument("--noise", type=float, default=0.0, help="fraction of extra unparseable lines, e.g. 0.01")
    parser.add_argument("--out", type=Path, default=Path("data/sample_logs"))
    args = parser.parse_args()

    if args.all:
        combos = [(c, d, s) for c in FAULTS for d in PROFILES for s in range(1, args.seeds + 1)]
    elif args.category and args.difficulty:
        combos = [(args.category, args.difficulty, args.seed)]
    else:
        parser.error("give --category and --difficulty, or --all")

    for category, difficulty, seed in combos:
        scenario = generate_scenario(category, difficulty, seed, args.noise)
        write_scenario(scenario, args.out)
        print(f"{scenario.labels.scenario_id}: {len(scenario.lines)} lines, root cause {scenario.labels.root_cause_service}")


if __name__ == "__main__":
    main()
