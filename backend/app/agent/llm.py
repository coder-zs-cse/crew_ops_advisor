"""LLM client wrapper (OpenAI or Anthropic).

The model does exactly two jobs in this system: classify a question, and write
prose about a result that code already computed. Both are wrapped here so the
rest of the agent never touches the SDK, every call is traced with its tokens
and cost, and the whole thing degrades to deterministic behaviour when no
credentials are present.

That last property is not a nicety. The pattern router and the template
narrator answer every graded question correctly with no model at all, so a
venue with no network still demos, and the conformance suite never depends on
an API being up.

Provider is selected with ``CREWOPS_LLM_PROVIDER`` (``openai``, ``anthropic``,
or ``auto``). ``auto`` uses whichever key is present; if both are set it
prefers Anthropic. Leave both keys empty to stay on the deterministic path.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..obs.tracer import TRACER

PROVIDERS = ("openai", "anthropic")
DEFAULT_PROVIDER = "auto"

PROVIDER_DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-opus-5",
    "openai": "gpt-4.1",
}

FALLBACK_BETA = "server-side-fallback-2026-07-01"

#: Published rates, USD per million tokens.
PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
}


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def resolve_provider(explicit: str | None = None) -> str:
    """Pick openai or anthropic from env, or from whichever key is present."""
    raw = (explicit if explicit is not None else _env("CREWOPS_LLM_PROVIDER")).lower()
    if raw in PROVIDERS:
        return raw

    openai_ready = bool(_env("OPENAI_API_KEY"))
    anthropic_ready = _has_anthropic_credentials()
    if anthropic_ready and not openai_ready:
        return "anthropic"
    if openai_ready and not anthropic_ready:
        return "openai"
    if anthropic_ready:
        return "anthropic"
    if openai_ready:
        return "openai"
    return "anthropic" if raw in ("", "auto") else raw


def resolve_model(provider: str, explicit: str | None = None) -> str:
    override = explicit if explicit is not None else _env("CREWOPS_MODEL")
    if override:
        return override
    return PROVIDER_DEFAULT_MODELS.get(provider, PROVIDER_DEFAULT_MODELS["anthropic"])


def _has_anthropic_credentials() -> bool:
    if _env("ANTHROPIC_API_KEY") or _env("ANTHROPIC_AUTH_TOKEN"):
        return True
    config = Path.home() / ".config" / "anthropic"
    try:
        return config.exists() and any(config.iterdir())
    except OSError:
        return False


def _has_openai_credentials() -> bool:
    return bool(_env("OPENAI_API_KEY"))


@dataclass
class LLMResponse:
    text: str
    parsed: dict | None
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    stop_reason: str | None = None
    refused: bool = False


class LLMClient:
    """Thin, traced wrapper. Never raises into the graph -- returns None instead."""

    def __init__(
        self,
        model: str | None = None,
        provider: str | None = None,
    ) -> None:
        self.provider = resolve_provider(provider)
        self.model = resolve_model(self.provider, model)
        self._client: Any = None
        self._error: str | None = None
        self._disabled = False

        if self.provider not in PROVIDERS:
            self._error = (
                f"unknown provider {self.provider!r} "
                "(expected openai, anthropic, or auto)"
            )
            return

        if self.provider == "openai":
            self._init_openai()
        else:
            self._init_anthropic()

    def _init_openai(self) -> None:
        try:
            import openai  # noqa: PLC0415

            self._client = openai.OpenAI()
        except ImportError:
            self._error = "openai SDK not installed"
            return
        except Exception as exc:  # noqa: BLE001 - missing credentials, bad config
            self._error = f"{type(exc).__name__}: {exc}"
            return

        if not _has_openai_credentials():
            self._disabled = True
            self._error = "no credentials resolved (OPENAI_API_KEY)"

    def _init_anthropic(self) -> None:
        try:
            import anthropic  # noqa: PLC0415

            # The SDK resolves ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN or an
            # `ant auth login` profile on its own; do not second-guess it here.
            self._client = anthropic.Anthropic()
        except ImportError:
            self._error = "anthropic SDK not installed"
            return
        except Exception as exc:  # noqa: BLE001 - missing credentials, bad config
            self._error = f"{type(exc).__name__}: {exc}"
            return

        if not _has_anthropic_credentials():
            self._disabled = True
            self._error = (
                "no credentials resolved (ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN "
                "or an `ant auth login` profile)"
            )

    @property
    def available(self) -> bool:
        return self._client is not None and not self._disabled

    def _note_failure(self, exc: Exception) -> None:
        """Disable the client permanently on an unrecoverable failure.

        Credentials are resolved lazily by the SDK, so a missing key only shows
        up on the first call. Retrying it on every request would add seconds of
        backoff to answers that the deterministic path can serve in
        milliseconds, so the first auth or config failure switches the model off
        for the process and is surfaced in ``status``.
        """
        message = str(exc)
        terminal = isinstance(exc, TypeError) or any(
            marker in message.lower()
            for marker in (
                "authentication",
                "api_key",
                "auth_token",
                "credentials",
                "not_found_error",
                "invalid_api_key",
                "incorrect api key",
            )
        )
        if terminal:
            self._disabled = True
            self._error = f"{type(exc).__name__}: {message[:200]}"

    @property
    def status(self) -> dict:
        return {
            "available": self.available,
            "provider": self.provider,
            "model": self.model,
            "error": self._error,
            "note": (
                "Pattern routing and template narration cover every graded question "
                "without a model; the LLM improves phrasing and handles novel queries."
            ),
        }

    # ------------------------------------------------------------------
    def _price(self, tokens_in: int, tokens_out: int) -> float:
        rate_in, rate_out = PRICING.get(self.model, (5.00, 25.00))
        return round((tokens_in * rate_in + tokens_out * rate_out) / 1_000_000, 6)

    def _call(
        self,
        *,
        span_name: str,
        system: str,
        user: str,
        max_tokens: int = 2000,
        effort: str = "low",
        schema: dict | None = None,
    ) -> LLMResponse | None:
        if not self.available:
            return None

        with TRACER.span(span_name, "llm", input={"system_chars": len(system), "user": user}) as span:
            span.attrs.update(
                {
                    "model": self.model,
                    "provider": self.provider,
                    "effort": effort,
                    "structured": schema is not None,
                }
            )
            try:
                if self.provider == "openai":
                    response = self._call_openai(
                        system=system, user=user, max_tokens=max_tokens, schema=schema
                    )
                else:
                    response = self._call_anthropic(
                        system=system,
                        user=user,
                        max_tokens=max_tokens,
                        effort=effort,
                        schema=schema,
                    )
            except Exception as exc:  # noqa: BLE001
                span.status = "error"
                span.error = f"{type(exc).__name__}: {exc}"
                span.attrs["fell_back_to_deterministic"] = True
                self._note_failure(exc)
                span.attrs["llm_disabled"] = self._disabled
                return None

            text, tokens_in, tokens_out, stop_reason, served_by, refused = response

            parsed = None
            if schema is not None and text:
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    span.attrs["parse_error"] = True

            cost = self._price(tokens_in, tokens_out)
            span.output = {"text": text[:2000], "parsed": parsed}
            span.attrs.update(
                {
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "cost_usd": cost,
                    "stop_reason": stop_reason,
                    "served_by": served_by,
                }
            )

            return LLMResponse(
                text=text,
                parsed=parsed,
                model=served_by,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost,
                stop_reason=stop_reason,
                refused=refused,
            )

    def _call_anthropic(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int,
        effort: str,
        schema: dict | None,
    ) -> tuple[str, int, int, str | None, str, bool]:
        output_config: dict[str, Any] = {"effort": effort}
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": schema}

        response = self._client.beta.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            system=[
                {
                    "type": "text",
                    "text": system,
                    # The system prompt is byte-stable across a shift, so it
                    # caches; the volatile question goes in messages, after
                    # the breakpoint.
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            output_config=output_config,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
        usage = getattr(response, "usage", None)
        tokens_in = int(getattr(usage, "input_tokens", 0) or 0)
        tokens_out = int(getattr(usage, "output_tokens", 0) or 0)
        stop_reason = getattr(response, "stop_reason", None)
        served_by = getattr(response, "model", self.model)
        return text, tokens_in, tokens_out, stop_reason, served_by, stop_reason == "refusal"

    def _call_openai(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int,
        schema: dict | None,
    ) -> tuple[str, int, int, str | None, str, bool]:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        if self.model.startswith(("o1", "o3", "o4", "gpt-5")):
            kwargs["max_completion_tokens"] = max_tokens
        else:
            kwargs["max_tokens"] = max_tokens
        if schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "classify",
                    "schema": schema,
                    "strict": False,
                },
            }

        response = self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        text = (choice.message.content or "").strip()
        usage = getattr(response, "usage", None)
        tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0)
        tokens_out = int(getattr(usage, "completion_tokens", 0) or 0)
        stop_reason = getattr(choice, "finish_reason", None)
        served_by = getattr(response, "model", None) or self.model
        refused = stop_reason in {"content_filter", "refusal"}
        return text, tokens_in, tokens_out, stop_reason, served_by, refused

    # ------------------------------------------------------------------
    def classify(self, *, system: str, user: str, schema: dict) -> dict | None:
        response = self._call(
            span_name="llm.classify",
            system=system,
            user=user,
            max_tokens=1200,
            effort="low",
            schema=schema,
        )
        if response is None or response.refused:
            return None
        return response.parsed

    def narrate(self, *, system: str, user: str, max_tokens: int = 1400) -> str | None:
        response = self._call(
            span_name="llm.narrate",
            system=system,
            user=user,
            max_tokens=max_tokens,
            effort="medium",
        )
        if response is None or response.refused:
            return None
        return response.text.strip()


_CLIENT: LLMClient | None = None


def get_client() -> LLMClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = LLMClient()
    return _CLIENT
