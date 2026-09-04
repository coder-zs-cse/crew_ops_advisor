"""Provider selection and credential gating — no live API calls."""

from __future__ import annotations

import pytest

from app.agent import llm as llm_mod
from app.agent.llm import LLMClient, resolve_model, resolve_provider


@pytest.fixture(autouse=True)
def _clear_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "CREWOPS_LLM_PROVIDER",
        "CREWOPS_MODEL",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(llm_mod, "_has_anthropic_credentials", lambda: False)


def test_auto_with_no_keys_defaults_to_anthropic_and_stays_offline() -> None:
    assert resolve_provider() == "anthropic"
    client = LLMClient()
    assert client.provider == "anthropic"
    assert client.model == "claude-opus-5"
    assert not client.available
    assert client.status["provider"] == "anthropic"


def test_auto_picks_openai_when_only_openai_key_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert resolve_provider() == "openai"
    client = LLMClient()
    assert client.provider == "openai"
    assert client.model == "gpt-4.1"
    assert client.available


def test_auto_picks_anthropic_when_only_anthropic_key_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(llm_mod, "_has_anthropic_credentials", lambda: True)
    assert resolve_provider() == "anthropic"
    client = LLMClient()
    assert client.provider == "anthropic"
    assert client.available


def test_explicit_openai_ignores_anthropic_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREWOPS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(llm_mod, "_has_anthropic_credentials", lambda: True)
    client = LLMClient()
    assert client.provider == "openai"
    assert not client.available
    assert "OPENAI_API_KEY" in (client.status["error"] or "")


def test_explicit_anthropic_ignores_openai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREWOPS_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    client = LLMClient()
    assert client.provider == "anthropic"
    assert not client.available


def test_model_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREWOPS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("CREWOPS_MODEL", "gpt-4o-mini")
    assert resolve_model("openai") == "gpt-4o-mini"
    client = LLMClient()
    assert client.model == "gpt-4o-mini"


def test_unknown_provider_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREWOPS_LLM_PROVIDER", "gemini")
    client = LLMClient()
    assert not client.available
    assert "unknown provider" in (client.status["error"] or "")
