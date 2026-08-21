"""
LLMProvider port (Clinova Phase 1, Epic 1.4, Story 1.4.1): the provider
abstraction ADR-004 calls for, extracted behind the existing, already-
proven Result[str, ErrorInfo] pattern in utils/azure_client.py rather than
inventing a new one.

utils/azure_client.py's AzureOpenAIClient becomes the first (NVIDIA NIM)
adapter satisfying this port -- STRUCTURALLY, via typing.Protocol, so this
extraction requires ZERO changes to azure_client.py itself. That file is
not touched by this story; every existing caller across pipeline/*.py
keeps working exactly as before (proven by the full test suite passing
unmodified) because nothing about its runtime behavior changed -- only a
new, independently-defined shape now happens to describe it.

03-system-architecture.md AD-2: this port is introduced now (Phase 1)
rather than deferred like VectorStore/GraphStore, because azure_client.py
already has real multi-model usage history to design the interface
against (pipeline/llm_council.py's 4 independently-tuned models) -- a
second implementation's worth of real usage patterns already exist, even
though a second literal *class* doesn't yet.
"""
from typing import Protocol, runtime_checkable

from utils.azure_client import Result


@runtime_checkable
class LLMProvider(Protocol):
    """Structural interface -- any object exposing these three methods
    with this call shape satisfies LLMProvider without inheriting from it.
    `isinstance(obj, LLMProvider)` checks method presence (not full type
    signatures -- Python's Protocol runtime check is structural-shallow),
    which is enough to prove genericity: see
    tests/test_llm_provider_port.py, which checks both AzureOpenAIClient
    and a second, independent, non-NVIDIA implementation against it."""

    def chat(self, system: str, user: str,
             temperature: float = 0.3, max_tokens: int = 4096) -> "Result[str]":
        ...

    def chat_json(self, system: str, user: str, max_tokens: int = 4096) -> "Result[str]":
        ...

    def vision(self, system: str, user_text: str,
               image_bytes: bytes, max_tokens: int = 2048) -> "Result[str]":
        ...
