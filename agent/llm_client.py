# agent/llm_client.py
"""
LLM Client — Shared Protocol + Multi-Provider Implementations

=== PROVIDERS SUPPORTED ===

1. Groq (default)   — groq package,  env: GROQ_API_KEY
   Models: openai/gpt-oss-120b, llama-3.3-70b-versatile, qwen/qwen3-32b,
           meta-llama/llama-4-scout-17b-16e-instruct, openai/gpt-oss-20b,
           llama-3.1-8b-instant  (tried strongest → weakest, auto-skips 429/400)

2. Gemini           — openai compat,  env: GEMINI_API_KEY
   Models: gemini-2.5-flash, gemini-2.0-flash, gemini-1.5-flash  (free tier: 1 M TPM)

3. OpenRouter       — openai compat,  env: OPENROUTER_API_KEY
   Models: meta-llama/llama-4-maverick:free, microsoft/mai-ds-r1:free,
           deepseek/deepseek-r1:free  (free models, no billing needed)

4. GitHub Models    — openai compat,  env: GITHUB_TOKEN
   Models: gpt-4o, Meta-Llama-3.1-70B-Instruct  (free with any GitHub account)

5. Anthropic/Claude — httpx direct,   env: ANTHROPIC_API_KEY
   Models: claude-haiku-4-5, claude-3-5-haiku-latest  ('wire in yourself')

=== CONFIGURATION (config.json llm block) ===

  Single provider (backward-compat):
    {"provider": "groq", "groq_api_key_env": "GROQ_API_KEY",
     "model": "llama-3.3-70b-versatile", "max_tokens": 800}

  Auto-detect (uses every provider whose key is found in env — recommended):
    {"provider": "auto", "max_tokens": 800}

  Explicit chain:
    {"provider": "chain",
     "chain": [
       {"provider": "groq",       "groq_api_key_env":      "GROQ_API_KEY"},
       {"provider": "gemini",     "gemini_api_key_env":    "GEMINI_API_KEY"},
       {"provider": "openrouter", "openrouter_api_key_env":"OPENROUTER_API_KEY"},
       {"provider": "github",     "github_token_env":      "GITHUB_TOKEN"},
       {"provider": "anthropic",  "anthropic_api_key_env": "ANTHROPIC_API_KEY"}
     ],
     "max_tokens": 800}

  Add keys to agent/groq.env (or any .env in the fallback chain) to activate.
"""

from __future__ import annotations

import os
import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

_DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"

# ---------------------------------------------------------------------------
# Per-model context budget (tokens per minute / context window).
# Used by GroundedGenerator to select the right schema tier so the total
# request (system + user + response) never exceeds the model's TPM limit.
#
# Tiers used in GroundedGenerator:
#   "full"    — SCHEMA_PROMPT        (~7800 tokens) → large models only
#   "compact" — SCHEMA_PROMPT_COMPACT (~1200 tokens) → any model ≥ 4k budget
#   "minimal" — SCHEMA_PROMPT_MINIMAL  (~400 tokens) → llama-3.1-8b-instant
#
# Values are conservative estimates to leave headroom for the response.
# ---------------------------------------------------------------------------
_MODEL_CONTEXT_BUDGET: dict[str, int] = {
    # ── Groq production models ──────────────────────────────────────────────
    "llama-3.3-70b-versatile":                    28_000,   # 128k ctx, ~30k TPM free
    "openai/gpt-oss-120b":                        20_000,   # 120B flagship
    "openai/gpt-oss-20b":                         20_000,   # 20B production
    "llama-3.1-8b-instant":                        4_000,   # 6k TPM — keep tight
    # ── Groq preview models ─────────────────────────────────────────────────
    "qwen/qwen3-32b":                             20_000,   # 32B, strong reasoning
    "meta-llama/llama-4-scout-17b-16e-instruct":  20_000,   # 17B, 750 tps
    # ── Google Gemini (free tier: 1 M TPM for flash) ────────────────────────
    "gemini-2.5-flash":                          900_000,
    "gemini-2.0-flash":                          900_000,
    "gemini-2.0-flash-lite":                     900_000,
    "gemini-1.5-flash":                          900_000,
    "gemini-1.5-pro":                          1_900_000,
    # ── OpenRouter free-tier models ──────────────────────────────────────────
    "meta-llama/llama-4-maverick:free":          130_000,
    "microsoft/mai-ds-r1:free":                  130_000,
    "deepseek/deepseek-r1:free":                 130_000,
    "google/gemini-2.0-flash-exp:free":          900_000,
    # ── GitHub Models (free with GitHub account) ─────────────────────────────
    "gpt-4o":                                    128_000,
    "Meta-Llama-3.1-70B-Instruct":               128_000,
    # ── Anthropic Claude ─────────────────────────────────────────────────────
    "claude-haiku-4-5":                          180_000,
    "claude-3-5-haiku-latest":                   180_000,
    "claude-3-haiku-20240307":                   180_000,
}
_DEFAULT_BUDGET = 8_000   # safe fallback for unknown models

# ---------------------------------------------------------------------------
# Updated fallback order (verified today from Groq docs)
# ---------------------------------------------------------------------------
_GROQ_MODELS_BY_POWER = [
    "openai/gpt-oss-120b",                         # 120B — most capable
    "llama-3.3-70b-versatile",                     # 70B — best quality
    "qwen/qwen3-32b",                              # 32B — strong reasoning (preview)
    "meta-llama/llama-4-scout-17b-16e-instruct",   # 17B — fast (preview)
    "openai/gpt-oss-20b",                          # 20B — production
    "llama-3.1-8b-instant",                        # 8B  — fast & reliable
]


# ---------------------------------------------------------------------------
# Shared Protocol (unchanged)
# ---------------------------------------------------------------------------

@runtime_checkable
class LLMClient(Protocol):
    def complete(self, *, system: str, message: str, max_tokens: int) -> str:
        ...


# ---------------------------------------------------------------------------
# GroqClient (only fallback list + comments updated)
# ---------------------------------------------------------------------------

class GroqClient:
    def __init__(
        self,
        api_key: str | None = None,
        model:   str        = _DEFAULT_GROQ_MODEL,
    ) -> None:
        try:
            import groq as _groq
            import httpx as _httpx
        except ImportError as exc:
            raise ImportError("groq package required. Install: pip install groq") from exc

        key = api_key or os.environ.get("GROQ_API_KEY", "")
        if not key:
            raise ValueError("Groq API key not found.")

        self._client = _groq.Groq(
            api_key=key,
            max_retries=0,
            timeout=_httpx.Timeout(30.0, connect=5.0),  # read=30s, connect=5s
        )

        preferred = model
        self._models: list[str] = [preferred]
        for m in _GROQ_MODELS_BY_POWER:
            if m not in self._models:
                self._models.append(m)

        logger.info(f"[GroqClient] initialized with fallback chain: {self._models}")
        # Track the last successfully used model for schema-tier selection
        self._current_model: str = preferred

    @property
    def current_model(self) -> str:
        """The last model that successfully completed a request."""
        return self._current_model

    @property
    def context_budget(self) -> int:
        """Estimated token budget for the current model's context window."""
        return _MODEL_CONTEXT_BUDGET.get(self._current_model, _DEFAULT_BUDGET)

    def complete(self, *, system: str, message: str, max_tokens: int) -> str:
        last_exception: Exception | None = None

        for model in self._models:
            try:
                logger.debug(f"[GroqClient] attempting completion with {model}")
                response = self._client.chat.completions.create(
                    model      = model,
                    max_tokens = max_tokens,
                    messages   = [
                        {"role": "system", "content": system},
                        {"role": "user",   "content": message},
                    ],
                )
                content = response.choices[0].message.content or ""
                self._current_model = model   # record which model succeeded
                logger.debug(f"[GroqClient] success with {model}")
                return content

            except Exception as exc:
                last_exception = exc
                error_str = str(exc).lower()
                status = getattr(exc, "status_code", getattr(exc, "code", None))

                is_rate_limit = "rate_limit" in error_str or "429" in error_str or status == 429
                is_decommissioned = (
                    "decommissioned" in error_str
                    or "model_decommissioned" in error_str
                    or (status == 400 and "model" in error_str)
                )

                if is_rate_limit or is_decommissioned:
                    logger.warning(
                        f"[GroqClient] {'RATE LIMIT' if is_rate_limit else 'MODEL DECOMMISSIONED'} "
                        f"on {model} — falling back to next model"
                    )
                    continue
                else:
                    logger.error(f"[GroqClient] non-recoverable error with {model}: {exc}")
                    raise

        logger.error(f"[GroqClient] ALL fallback models exhausted. Last error: {last_exception}")
        if last_exception:
            raise last_exception
        raise RuntimeError("All Groq models failed")


# ---------------------------------------------------------------------------
# GeminiClient — Google Gemini via OpenAI-compatible endpoint
# Free tier: 15 RPM / 1 M TPD on gemini-2.0-flash  (no billing required)
# ---------------------------------------------------------------------------

class GeminiClient:
    _BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
    _FALLBACK_MODELS = [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-2.0-flash-lite",
    ]

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash") -> None:
        try:
            import openai as _openai
        except ImportError as exc:
            raise ImportError("openai package required: pip install openai") from exc
        self._client = _openai.OpenAI(api_key=api_key, base_url=self._BASE_URL)
        self._models: list[str] = [model] + [m for m in self._FALLBACK_MODELS if m != model]
        self._current_model = model
        logger.info(f"[GeminiClient] chain: {self._models}")

    @property
    def current_model(self) -> str:
        return self._current_model

    @property
    def context_budget(self) -> int:
        return _MODEL_CONTEXT_BUDGET.get(self._current_model, 900_000)

    def complete(self, *, system: str, message: str, max_tokens: int) -> str:
        last_exc: Exception | None = None
        for model in self._models:
            try:
                resp = self._client.chat.completions.create(
                    model=model,
                    max_tokens=max_tokens,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user",   "content": message},
                    ],
                )
                self._current_model = model
                return resp.choices[0].message.content or ""
            except Exception as exc:
                last_exc = exc
                status = getattr(exc, "status_code", getattr(exc, "code", None))
                if "rate_limit" in str(exc).lower() or status == 429:
                    logger.warning(f"[GeminiClient] rate-limit on {model} — next")
                    continue
                raise
        raise last_exc or RuntimeError("All Gemini models failed")


# ---------------------------------------------------------------------------
# OpenRouterClient — free open-weight models via OpenRouter
# Sign-up at openrouter.ai — free models need no credit card
# ---------------------------------------------------------------------------

class OpenRouterClient:
    _BASE_URL = "https://openrouter.ai/api/v1"
    _FALLBACK_MODELS = [
        "meta-llama/llama-4-maverick:free",
        "google/gemini-2.0-flash-exp:free",
        "microsoft/mai-ds-r1:free",
        "deepseek/deepseek-r1:free",
    ]

    def __init__(self, api_key: str, model: str = "meta-llama/llama-4-maverick:free") -> None:
        try:
            import openai as _openai
        except ImportError as exc:
            raise ImportError("openai package required: pip install openai") from exc
        self._client = _openai.OpenAI(
            api_key=api_key,
            base_url=self._BASE_URL,
            default_headers={
                "HTTP-Referer": "https://github.com/kos-pid",
                "X-Title": "KOS-PID Agent",
            },
        )
        self._models: list[str] = [model] + [m for m in self._FALLBACK_MODELS if m != model]
        self._current_model = model
        logger.info(f"[OpenRouterClient] chain: {self._models}")

    @property
    def current_model(self) -> str:
        return self._current_model

    @property
    def context_budget(self) -> int:
        return _MODEL_CONTEXT_BUDGET.get(self._current_model, 130_000)

    def complete(self, *, system: str, message: str, max_tokens: int) -> str:
        last_exc: Exception | None = None
        for model in self._models:
            try:
                resp = self._client.chat.completions.create(
                    model=model,
                    max_tokens=max_tokens,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user",   "content": message},
                    ],
                )
                self._current_model = model
                return resp.choices[0].message.content or ""
            except Exception as exc:
                last_exc = exc
                status = getattr(exc, "status_code", getattr(exc, "code", None))
                if "rate_limit" in str(exc).lower() or status == 429:
                    logger.warning(f"[OpenRouterClient] rate-limit on {model} — next")
                    continue
                raise
        raise last_exc or RuntimeError("All OpenRouter models failed")


# ---------------------------------------------------------------------------
# GitHubModelsClient — free inference via GitHub Models
# Needs a GitHub personal-access token (PAT) — no billing, no card required
# ---------------------------------------------------------------------------

class GitHubModelsClient:
    _BASE_URL = "https://models.inference.ai.azure.com"
    _FALLBACK_MODELS = [
        "gpt-4o",
        "Meta-Llama-3.1-70B-Instruct",
        "Phi-3.5-MoE-instruct",
    ]

    def __init__(self, token: str, model: str = "gpt-4o") -> None:
        try:
            import openai as _openai
        except ImportError as exc:
            raise ImportError("openai package required: pip install openai") from exc
        self._client = _openai.OpenAI(api_key=token, base_url=self._BASE_URL)
        self._models: list[str] = [model] + [m for m in self._FALLBACK_MODELS if m != model]
        self._current_model = model
        logger.info(f"[GitHubModelsClient] chain: {self._models}")

    @property
    def current_model(self) -> str:
        return self._current_model

    @property
    def context_budget(self) -> int:
        return _MODEL_CONTEXT_BUDGET.get(self._current_model, 128_000)

    def complete(self, *, system: str, message: str, max_tokens: int) -> str:
        last_exc: Exception | None = None
        for model in self._models:
            try:
                resp = self._client.chat.completions.create(
                    model=model,
                    max_tokens=max_tokens,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user",   "content": message},
                    ],
                )
                self._current_model = model
                return resp.choices[0].message.content or ""
            except Exception as exc:
                last_exc = exc
                status = getattr(exc, "status_code", getattr(exc, "code", None))
                if "rate_limit" in str(exc).lower() or status == 429:
                    logger.warning(f"[GitHubModelsClient] rate-limit on {model} — next")
                    continue
                raise
        raise last_exc or RuntimeError("All GitHub Models models failed")


# ---------------------------------------------------------------------------
# AnthropicClient — Claude via Anthropic API (httpx, no extra package needed)
# "wire in yourself" — Claude Haiku has a free trial tier
# ---------------------------------------------------------------------------

class AnthropicClient:
    _API_URL = "https://api.anthropic.com/v1/messages"
    _API_VERSION = "2023-06-01"
    _FALLBACK_MODELS = [
        "claude-haiku-4-5",
        "claude-3-5-haiku-latest",
        "claude-3-haiku-20240307",
    ]

    def __init__(self, api_key: str, model: str = "claude-haiku-4-5") -> None:
        try:
            import httpx as _httpx
            self._httpx = _httpx
        except ImportError as exc:
            raise ImportError("httpx package required: pip install httpx") from exc
        self._api_key = api_key
        self._models: list[str] = [model] + [m for m in self._FALLBACK_MODELS if m != model]
        self._current_model = model
        logger.info(f"[AnthropicClient] chain: {self._models}")

    @property
    def current_model(self) -> str:
        return self._current_model

    @property
    def context_budget(self) -> int:
        return _MODEL_CONTEXT_BUDGET.get(self._current_model, 180_000)

    def complete(self, *, system: str, message: str, max_tokens: int) -> str:
        last_exc: Exception | None = None
        for model in self._models:
            try:
                resp = self._httpx.post(
                    self._API_URL,
                    headers={
                        "x-api-key":         self._api_key,
                        "anthropic-version": self._API_VERSION,
                        "content-type":      "application/json",
                    },
                    json={
                        "model":      model,
                        "max_tokens": max_tokens,
                        "system":     system,
                        "messages":   [{"role": "user", "content": message}],
                    },
                    timeout=30.0,
                )
                if resp.status_code in (429, 529):
                    logger.warning(f"[AnthropicClient] rate-limit/overload on {model} — next")
                    last_exc = RuntimeError(f"HTTP {resp.status_code} on {model}")
                    continue
                resp.raise_for_status()
                self._current_model = model
                return resp.json()["content"][0]["text"]
            except Exception as exc:
                last_exc = exc
                if "rate_limit" in str(exc).lower() or "529" in str(exc) or "429" in str(exc):
                    logger.warning(f"[AnthropicClient] rate-limit on {model} — next")
                    continue
                raise
        raise last_exc or RuntimeError("All Anthropic models failed")


# ---------------------------------------------------------------------------
# ChainedProviderClient — multi-provider fallback wrapper
# Tries each client in order; first success wins. Updates active client so
# context_budget / current_model always reflect the last successful provider.
# ---------------------------------------------------------------------------

class ChainedProviderClient:
    def __init__(self, clients: list) -> None:
        if not clients:
            raise ValueError("ChainedProviderClient requires at least one client")
        self._clients: list = clients
        self._active = clients[0]

    @property
    def current_model(self) -> str:
        return getattr(self._active, "current_model", "unknown")

    @property
    def context_budget(self) -> int:
        return getattr(self._active, "context_budget", _DEFAULT_BUDGET)

    def complete(self, *, system: str, message: str, max_tokens: int) -> str:
        last_exc: Exception | None = None
        for client in self._clients:
            try:
                result = client.complete(system=system, message=message, max_tokens=max_tokens)
                self._active = client
                return result
            except Exception as exc:
                logger.warning(
                    f"[ChainedProviderClient] {type(client).__name__} failed: {exc} — trying next provider"
                )
                last_exc = exc
        logger.error("[ChainedProviderClient] ALL providers exhausted.")
        raise last_exc or RuntimeError("All LLM providers failed")


# ---------------------------------------------------------------------------
# Config-driven factory
# ---------------------------------------------------------------------------

# Default auto-detect order: tried when provider == "auto"
_AUTO_PROVIDER_CONFIGS: list[dict] = [
    {"provider": "groq",       "groq_api_key_env":       "GROQ_API_KEY",
     "model": "llama-3.3-70b-versatile"},
    {"provider": "gemini",     "gemini_api_key_env":      "GEMINI_API_KEY",
     "model": "gemini-2.5-flash"},
    {"provider": "openrouter", "openrouter_api_key_env":  "OPENROUTER_API_KEY",
     "model": "meta-llama/llama-4-maverick:free"},
    {"provider": "github",     "github_token_env":        "GITHUB_TOKEN",
     "model": "gpt-4o"},
    {"provider": "anthropic",  "anthropic_api_key_env":   "ANTHROPIC_API_KEY",
     "model": "claude-haiku-4-5"},
]


def _build_single_provider(cfg: dict) -> "LLMClient | None":
    """Construct one provider client from a sub-config dict. Returns None on failure."""
    provider = cfg.get("provider", "groq").lower()

    if provider == "groq":
        key_env = cfg.get("groq_api_key_env", "GROQ_API_KEY")
        api_key = os.environ.get(key_env, "")
        model   = cfg.get("model", _DEFAULT_GROQ_MODEL)
        if not api_key:
            logger.debug(f"[LLMClient] {key_env} not set — skipping Groq")
            return None
        try:
            return GroqClient(api_key=api_key, model=model)
        except Exception as exc:
            logger.warning(f"[LLMClient] GroqClient init failed: {exc}")
            return None

    if provider == "gemini":
        key_env = cfg.get("gemini_api_key_env", "GEMINI_API_KEY")
        api_key = os.environ.get(key_env, "")
        model   = cfg.get("model", "gemini-2.5-flash")
        if not api_key:
            logger.debug(f"[LLMClient] {key_env} not set — skipping Gemini")
            return None
        try:
            return GeminiClient(api_key=api_key, model=model)
        except Exception as exc:
            logger.warning(f"[LLMClient] GeminiClient init failed: {exc}")
            return None

    if provider == "openrouter":
        key_env = cfg.get("openrouter_api_key_env", "OPENROUTER_API_KEY")
        api_key = os.environ.get(key_env, "")
        model   = cfg.get("model", "meta-llama/llama-4-maverick:free")
        if not api_key:
            logger.debug(f"[LLMClient] {key_env} not set — skipping OpenRouter")
            return None
        try:
            return OpenRouterClient(api_key=api_key, model=model)
        except Exception as exc:
            logger.warning(f"[LLMClient] OpenRouterClient init failed: {exc}")
            return None

    if provider == "github":
        token_env = cfg.get("github_token_env", "GITHUB_TOKEN")
        token     = os.environ.get(token_env, "")
        model     = cfg.get("model", "gpt-4o")
        if not token:
            logger.debug(f"[LLMClient] {token_env} not set — skipping GitHub Models")
            return None
        try:
            return GitHubModelsClient(token=token, model=model)
        except Exception as exc:
            logger.warning(f"[LLMClient] GitHubModelsClient init failed: {exc}")
            return None

    if provider == "anthropic":
        key_env = cfg.get("anthropic_api_key_env", "ANTHROPIC_API_KEY")
        api_key = os.environ.get(key_env, "")
        model   = cfg.get("model", "claude-haiku-4-5")
        if not api_key:
            logger.debug(f"[LLMClient] {key_env} not set — skipping Anthropic/Claude")
            return None
        try:
            return AnthropicClient(api_key=api_key, model=model)
        except Exception as exc:
            logger.warning(f"[LLMClient] AnthropicClient init failed: {exc}")
            return None

    logger.warning(f"[LLMClient] Unknown provider '{provider}' — skipping")
    return None


def build_llm_client_from_config(llm_cfg: dict) -> "LLMClient | None":
    provider = llm_cfg.get("provider", "groq").lower()

    # ── Explicit chain ────────────────────────────────────────────────────────
    if provider == "chain":
        clients = [
            c for sub in llm_cfg.get("chain", [])
            if (c := _build_single_provider(sub)) is not None
        ]
        if not clients:
            logger.warning("[LLMClient] No providers in chain succeeded — LLM disabled.")
            return None
        return clients[0] if len(clients) == 1 else ChainedProviderClient(clients)

    # ── Auto-detect (recommended) ─────────────────────────────────────────────
    if provider == "auto":
        clients = [
            c for sub in _AUTO_PROVIDER_CONFIGS
            if (c := _build_single_provider(sub)) is not None
        ]
        if not clients:
            logger.warning("[LLMClient] No API keys found for any provider — LLM disabled.")
            return None
        names = [type(c).__name__ for c in clients]
        logger.info(f"[LLMClient] Auto-detected {len(clients)} provider(s): {names}")
        return clients[0] if len(clients) == 1 else ChainedProviderClient(clients)

    # ── Single provider (backward-compatible) ─────────────────────────────────
    client = _build_single_provider(llm_cfg)
    if client is None:
        logger.warning(f"[LLMClient] Provider '{provider}' not available — LLM disabled.")
    return client