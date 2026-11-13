import pytest

from log_triage.llm import DEFAULT_MODEL, build_llm, model_id


@pytest.fixture(autouse=True)
def fake_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "test-key")  # building an LLM makes no network call


@pytest.mark.parametrize("value", [None, ""])
def test_unset_or_empty_model_falls_back_to_the_default(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    if value is None:
        monkeypatch.delenv("GROQ_MODEL", raising=False)
    else:
        monkeypatch.setenv("GROQ_MODEL", value)
    assert model_id() == DEFAULT_MODEL


def test_the_model_reaches_groq_with_exactly_one_openai_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_MODEL", "qwen/qwen3.8-27b")
    assert build_llm().model == "qwen/qwen3.8-27b"  # custom_openai strips the one prefix build_llm adds


@pytest.mark.parametrize("value", [None, ""])
def test_a_missing_key_fails_early_with_a_clear_message(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    if value is None:
        monkeypatch.delenv("GROQ_API_KEY")
    else:
        monkeypatch.setenv("GROQ_API_KEY", value)
    with pytest.raises(RuntimeError, match="GROQ_API_KEY is not set"):
        build_llm()


def test_every_call_builds_a_new_llm_object() -> None:
    assert build_llm() is not build_llm()  # shared objects would double-count tokens
