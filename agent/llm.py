"""
agent/llm.py
-------------
LLM client abstraction for Pitchproof.

Provider is selected via the LLM_PROVIDER environment variable:
  - "watsonx"  (default) — IBM watsonx.ai using ibm-watsonx-ai SDK
  - "openai"             — OpenAI-compatible endpoint (fallback / local)

Usage (inside any agent node):
    from agent.llm import get_llm_client
    llm = get_llm_client()
    response = llm.invoke("Explain this error: ...")

No API calls are made at import time.  The client is instantiated lazily
the first time get_llm_client() is called.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dotenv import load_dotenv

load_dotenv()
from functools import lru_cache
from typing import Optional


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class LLMClient(ABC):
    """Minimal interface every provider adapter must implement."""

    @abstractmethod
    def invoke(self, prompt: str, *, max_tokens: int = 1024, temperature: float = 0.2) -> str:
        """
        Send *prompt* to the LLM and return the text response.

        Args:
            prompt:      The full prompt string.
            max_tokens:  Maximum tokens to generate.
            temperature: Sampling temperature (lower = more deterministic).

        Returns:
            The model's text response as a plain string.
        """

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the client can reach its backend (credentials present)."""


# ---------------------------------------------------------------------------
# IBM watsonx.ai adapter
# ---------------------------------------------------------------------------

class WatsonxClient(LLMClient):
    """
    Thin wrapper around ibm-watsonx-ai ModelInference.

    Required environment variables (see .env.example):
        WATSONX_API_KEY
        WATSONX_PROJECT_ID
        WATSONX_URL          (defaults to us-south endpoint)
        WATSONX_MODEL_ID     (defaults to ibm/granite-34b-code-instruct)
    """

    DEFAULT_URL      = "https://us-south.ml.cloud.ibm.com"
    DEFAULT_MODEL_ID = "ibm/granite-34b-code-instruct"

    def __init__(self) -> None:
        self._api_key    = os.environ.get("WATSONX_API_KEY", "")
        self._project_id = os.environ.get("WATSONX_PROJECT_ID", "")
        self._url        = os.environ.get("WATSONX_URL", self.DEFAULT_URL)
        self._model_id   = os.environ.get("WATSONX_MODEL_ID", self.DEFAULT_MODEL_ID)
        self._model: Optional[object] = None   # ibm_watsonx_ai.ModelInference, lazy

    def is_available(self) -> bool:
        return bool(self._api_key and self._project_id)

    def _get_model(self) -> object:
        """Lazy-instantiate the watsonx.ai ModelInference client."""
        if self._model is None:
            try:
                from ibm_watsonx_ai import Credentials
                from ibm_watsonx_ai.foundation_models import ModelInference
                from ibm_watsonx_ai.metanames import GenTextParamsMetaNames as GenParams

                credentials = Credentials(url=self._url, api_key=self._api_key)
                self._model = ModelInference(
                    model_id=self._model_id,
                    credentials=credentials,
                    project_id=self._project_id,
                    params={
                        GenParams.DECODING_METHOD: "greedy",
                        GenParams.STOP_SEQUENCES:  [],
                    },
                )
            except ImportError as exc:
                raise RuntimeError(
                    "ibm-watsonx-ai is not installed. "
                    "Run: pip install ibm-watsonx-ai"
                ) from exc
        return self._model

    def invoke(self, prompt: str, *, max_tokens: int = 1024, temperature: float = 0.2) -> str:
        from ibm_watsonx_ai.metanames import GenTextParamsMetaNames as GenParams

        model = self._get_model()
        params = {
            GenParams.MAX_NEW_TOKENS: max_tokens,
            GenParams.TEMPERATURE:    temperature,
        }
        result = model.generate_text(prompt=prompt, params=params)  # type: ignore[union-attr]
        return result if isinstance(result, str) else str(result)


# ---------------------------------------------------------------------------
# OpenAI-compatible adapter  (fallback / local models via LM Studio, Ollama, …)
# ---------------------------------------------------------------------------

class OpenAIClient(LLMClient):
    """
    Wrapper around the openai Python SDK.

    Required environment variables (see .env.example):
        OPENAI_API_KEY
        OPENAI_MODEL_ID   (e.g. "gpt-4o", "deepseek-coder", …)
        OPENAI_BASE_URL   (optional — for non-OpenAI endpoints)
    """

    DEFAULT_MODEL_ID = "gpt-4o"

    def __init__(self) -> None:
        self._api_key  = os.environ.get("OPENAI_API_KEY", "")
        self._model_id = os.environ.get("OPENAI_MODEL_ID", self.DEFAULT_MODEL_ID)
        self._base_url = os.environ.get("OPENAI_BASE_URL") or None   # None = use default
        self._client: Optional[object] = None  # openai.OpenAI, lazy

    def is_available(self) -> bool:
        return bool(self._api_key)

    def _get_client(self) -> object:
        if self._client is None:
            try:
                import openai  # type: ignore[import]

                kwargs: dict = {"api_key": self._api_key}
                if self._base_url:
                    kwargs["base_url"] = self._base_url
                self._client = openai.OpenAI(**kwargs)
            except ImportError as exc:
                raise RuntimeError(
                    "openai package is not installed. Run: pip install openai"
                ) from exc
        return self._client

    def invoke(self, prompt: str, *, max_tokens: int = 1024, temperature: float = 0.2) -> str:
        client = self._get_client()
        response = client.chat.completions.create(  # type: ignore[union-attr]
            model=self._model_id,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Stub adapter — used in tests / when no credentials are configured
# ---------------------------------------------------------------------------

class StubLLMClient(LLMClient):
    """
    Returns deterministic canned responses.
    Safe to use in tests and CI without any real credentials.
    """

    def is_available(self) -> bool:
        return True

    def invoke(self, prompt: str, *, max_tokens: int = 1024, temperature: float = 0.2) -> str:
        # Return a minimal structured response that every node can parse.
        return (
            "[STUB] LLM not configured. "
            "Set WATSONX_API_KEY + WATSONX_PROJECT_ID (or OPENAI_API_KEY) in .env "
            "to enable real model responses."
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_llm_client() -> LLMClient:
    """
    Return the configured LLM client (singleton).

    Resolution order:
      1. LLM_PROVIDER env var overrides automatic detection.
      2. If WATSONX_API_KEY + WATSONX_PROJECT_ID are set → WatsonxClient.
      3. If OPENAI_API_KEY is set → OpenAIClient.
      4. Fallback → StubLLMClient (logs a warning).
    """
    provider = os.environ.get("LLM_PROVIDER", "auto").lower()

    if provider == "watsonx":
        return WatsonxClient()
    if provider == "openai":
        return OpenAIClient()

    # Auto-detect from available credentials
    watsonx = WatsonxClient()
    if watsonx.is_available():
        return watsonx

    openai_client = OpenAIClient()
    if openai_client.is_available():
        return openai_client

    import warnings
    warnings.warn(
        "No LLM credentials found. Using StubLLMClient. "
        "Configure WATSONX_API_KEY / OPENAI_API_KEY in .env to enable real LLM calls.",
        stacklevel=2,
    )
    return StubLLMClient()
