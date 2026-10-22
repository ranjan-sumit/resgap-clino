"""Scripted stand-in for AzureOpenAIClient / ModelRouter clients.

Replies are consumed in order. An item is a str (success), a dict/list (JSON
success), or an Exception / Failure instance (failure). When the script runs
out, `default` is returned. Every call is recorded in `.calls`.
"""
from __future__ import annotations

import json
from typing import Any

from utils.azure_client import ErrorInfo, Failure, Success


class FakeClient:
    def __init__(self, replies: list[Any] | None = None, default: Any = "{}",
                 model: str = "fake-model"):
        self._replies = list(replies or [])
        self._default = default
        self.model = model
        self.calls: list[dict] = []
        self.stage = ""

    def set_stage(self, stage: str) -> None:
        self.stage = stage

    def _next(self, kind: str, system: str, user: str):
        self.calls.append({"kind": kind, "stage": self.stage, "system": system, "user": user})
        item = self._replies.pop(0) if self._replies else self._default
        if isinstance(item, Failure):
            return item
        if isinstance(item, str) and item.startswith("!"):
            kind_name = item[1:] or "api_error"
            return Failure(ErrorInfo(kind=kind_name, detail="scripted failure"))
        if isinstance(item, BaseException):
            raise item
        return Success(item if isinstance(item, str) else json.dumps(item))

    def chat(self, system, user, *a, **kw):
        return self._next("chat", system, user)

    def chat_json(self, system, user, *a, **kw):
        return self._next("chat_json", system, user)

    def vision(self, system, user_text, *a, **kw):
        return self._next("vision", system, user_text)
