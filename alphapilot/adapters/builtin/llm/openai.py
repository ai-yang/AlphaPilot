"""Built-in LLM adapter that wraps the legacy ``APIBackend``.

The existing :class:`alphapilot.oai.llm_utils.APIBackend` already handles
OpenAI / Azure / GCR / llama backends. We keep it as the concrete
implementation but expose it through the unified :class:`BaseLLMAdapter`
interface so callers can switch providers without touching business code.
"""

from __future__ import annotations

from typing import Any

from alphapilot.adapters.base import (
    BaseLLMAdapter,
    ChatRequest,
    ChatResponse,
    EmbeddingResponse,
)
from alphapilot.adapters.registry import LLM_REGISTRY


@LLM_REGISTRY.register("openai", is_default=True)
class APIBackendLLMAdapter(BaseLLMAdapter):
    """Delegates to :class:`APIBackend` for actual LLM calls.

    Instantiation is lazy so importing this module does not require the
    LLM credentials to be present.
    """

    def __init__(self, **api_backend_kwargs: Any) -> None:
        self._api_backend_kwargs = api_backend_kwargs
        self._backend: Any | None = None

    @property
    def backend(self) -> Any:
        if self._backend is None:
            from alphapilot.oai.llm_utils import APIBackend

            self._backend = APIBackend(**self._api_backend_kwargs)
        return self._backend

    def chat(self, request: ChatRequest) -> ChatResponse:
        former_messages = [
            {"role": m.role, "content": m.content} for m in request.history
        ]
        content = self.backend.build_messages_and_create_chat_completion(
            user_prompt=request.user_prompt,
            system_prompt=request.system_prompt,
            former_messages=former_messages or None,
            **request.extra,
        )
        return ChatResponse(content=content, raw=content)

    def embed(self, inputs: list[str]) -> EmbeddingResponse:
        vectors = self.backend.create_embedding(inputs)
        if not isinstance(vectors, list):
            vectors = [vectors]
        return EmbeddingResponse(vectors=vectors, raw=vectors)
