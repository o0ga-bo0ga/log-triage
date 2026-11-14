"""Running an agent's crew with retries that also cover rejections by the LLM provider.

Two things can reject an answer: our guardrail (a cited line is wrong) and the provider itself. Some providers check
the JSON schema only AFTER the model has written its answer (seen on Groq: "maxItems: got 10, want 8"), and that
arrives as an API error which crewai's own guardrail retries never see. So this one loop handles both: it builds a
fresh crew, and on a retryable rejection tries again with the rejection fed back through the `{feedback}`
placeholder every agent task ends with. crewai's guardrail retries are set to 0, so the budget is counted only here.
"""

from collections.abc import Callable
from dataclasses import dataclass

from crewai import Crew, CrewOutput

# Rejections a second attempt can fix: the provider found the output's shape wrong, or our guardrail found a problem.
# Anything else (bad key, network, rate limit after the client's own retries) would only fail again.
RETRYABLE = ("json_validate_failed", "guardrail validation")
MAX_FEEDBACK_CHARS = 2000  # a provider error can quote a whole truncated answer; the model needs the reason, not that


@dataclass(frozen=True)
class Attempted:
    output: CrewOutput | None  # the successful attempt's output, or None
    error: str | None  # why the last attempt failed, when output is None
    attempts: int  # how many attempts ran; more than 1 means a retry happened (worth counting in evals)


def feedback_for(error: str) -> str:
    return "YOUR PREVIOUS ANSWER WAS REJECTED. Fix this and answer again:\n" + error[:MAX_FEEDBACK_CHARS]


def kickoff_with_retries(build_crew: Callable[[], Crew], inputs: dict[str, str], max_attempts: int) -> Attempted:
    feedback = ""
    for attempt in range(1, max_attempts + 1):
        try:
            # A fresh crew per attempt: new LLM objects, so token counts belong to this attempt only.
            return Attempted(output=build_crew().kickoff(inputs={**inputs, "feedback": feedback}), error=None, attempts=attempt)
        except Exception as e:
            error = str(e)
            if attempt == max_attempts or not any(marker in error for marker in RETRYABLE):
                return Attempted(output=None, error=error, attempts=attempt)
            feedback = feedback_for(error)
    raise AssertionError("unreachable: the loop always returns")
