from typing import Any

from log_triage.attempts import MAX_FEEDBACK_CHARS, kickoff_with_retries


class FakeCrew:
    """Stands in for a Crew: replays a script of outcomes, one per kickoff, and records what it was given."""

    def __init__(self, script: list[Any], seen: list[dict[str, str]]) -> None:
        self.script, self.seen = script, seen

    def kickoff(self, inputs: dict[str, str]) -> Any:
        self.seen.append(inputs)
        outcome = self.script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def run(script: list[Any], max_attempts: int = 3) -> tuple[Any, list[dict[str, str]]]:
    seen: list[dict[str, str]] = []
    result = kickoff_with_retries(lambda: FakeCrew(script, seen), {"digest": "d"}, max_attempts)  # type: ignore[arg-type,return-value]
    return result, seen


def test_success_first_time_needs_no_feedback() -> None:
    result, seen = run(["ok"])
    assert (result.output, result.error, result.attempts) == ("ok", None, 1)
    assert seen == [{"digest": "d", "feedback": ""}]


def test_a_provider_schema_rejection_is_retried_with_the_reason() -> None:
    result, seen = run([Exception("400 json_validate_failed: maxItems: got 10, want 8"), "ok"])
    assert result.output == "ok" and result.attempts == 2
    assert "maxItems: got 10, want 8" in seen[1]["feedback"]


def test_a_guardrail_failure_is_retried() -> None:
    result, _ = run([Exception("Task failed guardrail validation after 0 retries. Last error: line 9"), "ok"])
    assert result.output == "ok"


def test_other_errors_are_not_retried() -> None:
    result, seen = run([Exception("401 invalid api key"), "never reached"])
    assert result.output is None and result.attempts == 1 and "401" in result.error
    assert len(seen) == 1


def test_the_budget_is_never_exceeded() -> None:
    result, seen = run([Exception("json_validate_failed")] * 5, max_attempts=3)
    assert result.output is None and result.attempts == 3 and len(seen) == 3


def test_long_errors_are_trimmed_before_going_back_to_the_model() -> None:
    _, seen = run([Exception("json_validate_failed " + "x" * 10_000), "ok"])
    assert len(seen[1]["feedback"]) < MAX_FEEDBACK_CHARS + 100
