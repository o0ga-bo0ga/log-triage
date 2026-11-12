"""Evidence pack for the fix suggestor: a small slice of the digest, chosen by plain Python. No LLM, no dependency map.

CrewAI hands the next task the previous answer as text only, so the suggestor would not otherwise see any log lines.
The pack holds what it needs to explain how the failure unfolded:
  - the services the classifier named as root-cause candidates, with the exact lines it cited, and
  - the next few services that had a sustained burst of WARN/ERROR lines, earliest first. Callers of the root cause
    show symptoms, so they tend to have an onset; this finds them from the logs alone, without knowing who calls whom.

Known weakness: an unrelated noisy service (a decoy) also has a burst and can be picked. Whether that misleads the
suggestor is for the evals to measure. A pack built from a dependency map is parked in docs/ideas.md.
"""

from log_triage.digest import render_service
from log_triage.schemas import ClassifiedIncident, Digest, LogEvent, ServiceDigest

MAX_EXTRA_SERVICES = 3  # a starting guess, to be tuned with evals


def select_services(incident: ClassifiedIncident, digest: Digest) -> tuple[list[ServiceDigest], list[ServiceDigest]]:
    """(candidate services in the classifier's rank order, extra services with an onset, earliest first)."""
    by_name = {s.service: s for s in digest.services}
    candidates: list[ServiceDigest] = []
    for candidate in incident.root_cause_candidates:
        service = by_name.get(candidate.service)  # an unknown service is the validator's problem, not ours
        if service is not None and service not in candidates:
            candidates.append(service)
    chosen = {s.service for s in candidates}
    # digest.services is already ordered by onset, earliest first, services without an onset last.
    extras = [s for s in digest.services if s.onset is not None and s.service not in chosen]
    return candidates, extras[:MAX_EXTRA_SERVICES]


def build_evidence(incident: ClassifiedIncident, digest: Digest, events: list[LogEvent]) -> str:
    candidates, extras = select_services(incident, digest)
    by_line = {e.line_number: e for e in events}
    out = ["Evidence from the log for explaining how the failure unfolded."]

    if candidates:
        out += ["", "Root cause candidates, best first. Lines the classifier cited:"]
        for rank, candidate in enumerate(incident.root_cause_candidates, start=1):
            out.append(f"  {rank}. {candidate.service} (confidence {candidate.confidence:.2f})")
            for number in candidate.evidence_lines:
                if number in by_line:
                    out.append(f"     line {number}: {by_line[number].raw}")
        for service in candidates:
            out += ["", *render_service(service)]
    else:
        out += ["", "The classifier named no root cause candidate."]

    if extras:
        out += ["", "Other services with a sustained burst of WARN/ERROR lines, earliest first:"]
        for service in extras:
            out += ["", *render_service(service)]

    shown = {s.service for s in candidates + extras}
    hidden = [s.service for s in digest.services if s.service not in shown]
    if hidden:
        out += ["", f"Not shown (no sustained burst, or beyond the first {MAX_EXTRA_SERVICES}): {', '.join(hidden)}"]
    return "\n".join(out)
