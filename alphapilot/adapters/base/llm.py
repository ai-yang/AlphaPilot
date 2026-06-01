"""Abstract interface for LLM providers.

Adapters wrap concrete LLM SDKs (OpenAI, Azure, llama, ...) behind a unified
API so that the rest of the codebase only depends on this abstraction.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatMessage:
    role: str
    content: str


@dataclass
class ChatRequest:
    user_prompt: str
    system_prompt: str | None = None
    history: list[ChatMessage] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatResponse:
    content: str
    raw: Any = None


@dataclass
class EmbeddingResponse:
    vectors: list[list[float]]
    raw: Any = None


class BaseLLMAdapter(ABC):
    """Unified interface to any LLM provider.

    Subclasses MUST implement :meth:`chat` and SHOULD implement
    :meth:`embed` when the backend supports embeddings.

    The other helpers (:meth:`chat_completion`, :meth:`count_tokens`,
    :meth:`chat_session`, :meth:`create_embedding`) exist so call sites
    can migrate from the legacy ``APIBackend`` API with minimal churn.
    Adapters that wrap a backend with a richer API should override them;
    by default they delegate to :meth:`chat` / :meth:`embed`.
    """

    name: str = ""

    @abstractmethod
    def chat(self, request: ChatRequest) -> ChatResponse:
        """Run a single chat completion request."""

    def embed(self, inputs: list[str]) -> EmbeddingResponse:  # pragma: no cover
        """Optional embedding endpoint. Override when supported."""
        raise NotImplementedError(
            f"{type(self).__name__} does not implement embed()."
        )

    def chat_text(
        self,
        user_prompt: str,
        system_prompt: str | None = None,
        **extra: Any,
    ) -> str:
        """Convenience helper that returns only the response text."""
        return self.chat(
            ChatRequest(
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                extra=extra,
            )
        ).content

    # ---- Drop-in replacements for legacy ``APIBackend`` API ----
    # These mirror the original method names so call sites can migrate
    # with a one-line change. Adapters with richer backends should
    # override them to take advantage of features such as chat caching,
    # session memory, or token counting.

    def chat_completion(
        self,
        user_prompt: str,
        system_prompt: str | None = None,
        former_messages: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> str:
        """Drop-in for ``build_messages_and_create_chat_completion``."""
        history: list[ChatMessage] = []
        if former_messages:
            history = [
                ChatMessage(role=m["role"], content=m["content"])
                for m in former_messages
            ]
        return self.chat(
            ChatRequest(
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                history=history,
                extra=kwargs,
            )
        ).content

    def count_tokens(
        self,
        user_prompt: str,
        system_prompt: str | None = None,
        former_messages: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> int:
        """Drop-in for ``build_messages_and_calculate_token``.

        Default implementation returns ``0``; adapters that can count
        tokens should override.
        """
        return 0

    def chat_session(
        self,
        system_prompt: str | None = None,
        conversation_id: str | None = None,
    ) -> Any:
        """Drop-in for ``build_chat_session``.

        ``conversation_id`` is honored only by adapters whose backend has
        native multi-turn persistence (e.g. ``APIBackend``). The default
        fallback ignores it and starts a fresh in-memory session.
        """
        return _SimpleChatSession(self, system_prompt)

    def create_embedding(self, input_content: str | list[str], **kwargs: Any) -> Any:
        """Drop-in for ``APIBackend.create_embedding``.

        Returns a single vector when ``input_content`` is ``str``,
        otherwise a list of vectors (mirrors the legacy behavior).
        """
        single = isinstance(input_content, str)
        inputs = [input_content] if single else list(input_content)
        resp = self.embed(inputs)
        if single:
            return resp.vectors[0]
        return resp.vectors


class _SimpleChatSession:
    """Minimal :meth:`BaseLLMAdapter.chat_session` fallback.

    Mirrors the surface used by callers of the legacy ``ChatSession``:
    ``build_chat_completion(user_prompt)`` and the system prompt.
    """

    def __init__(self, adapter: "BaseLLMAdapter", system_prompt: str | None) -> None:
        self._adapter = adapter
        self._system_prompt = system_prompt
        self._history: list[ChatMessage] = []

    def build_chat_completion(self, user_prompt: str, **kwargs: Any) -> str:
        resp = self._adapter.chat(
            ChatRequest(
                user_prompt=user_prompt,
                system_prompt=self._system_prompt,
                history=list(self._history),
                extra=kwargs,
            )
        )
        self._history.append(ChatMessage(role="user", content=user_prompt))
        self._history.append(ChatMessage(role="assistant", content=resp.content))
        return resp.content
