"""Per-run log of model calls.

One record per call attempt (including fallback attempts): stage, provider,
model, latency, outcome and a prompt hash. Prompts are never stored unless
`keep_prompts` is on. API keys are redacted from every stored string, and the
log is capped so a runaway run cannot fill the disk.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time

MAX_RECORDS = 5000
MAX_DETAIL_CHARS = 500
_KEY_SHAPES = re.compile(r"(AIza[0-9A-Za-z_\-]{20,}|AQ\.[0-9A-Za-z_\-]{20,}|nvapi-[0-9A-Za-z_\-]{10,}|"
                         r"gsk_[0-9A-Za-z]{10,}|sk-[0-9A-Za-z_\-]{16,}|s2k-[0-9A-Za-z_\-]{10,})")


class CallLog:
    def __init__(self, secrets=(), keep_prompts: bool = False, max_records: int = MAX_RECORDS):
        self._secrets = [s for s in secrets if s and len(s) >= 8]
        self.keep_prompts = keep_prompts
        self.max_records = max_records
        self.records: list[dict] = []
        self.dropped = 0
        self.schema_errors: list[dict] = []        # items an agent returned in the wrong shape (rejected)
        self.schema_error_count = 0
        self._lock = threading.Lock()

    def redact(self, text) -> str:
        text = str(text or "")
        for s in self._secrets:
            text = text.replace(s, "[redacted]")
        return _KEY_SHAPES.sub("[redacted]", text)[:MAX_DETAIL_CHARS]

    def record(self, *, stage, provider, model, method, system, user, started: float,
               ok: bool, error_kind: str = "", error_detail: str = "", response_chars: int = 0) -> None:
        rec = {
            "ts": round(started, 3), "stage": stage or "", "provider": provider, "model": model,
            "method": method, "latency_s": round(time.time() - started, 2), "ok": ok,
            "error_kind": error_kind, "error": self.redact(error_detail),
            "prompt_sha256": hashlib.sha256(f"{system}\n{user}".encode("utf-8", "replace")).hexdigest()[:16],
            "prompt_chars": len(system or "") + len(user or ""), "response_chars": response_chars,
        }
        if self.keep_prompts:
            rec["system"], rec["user"] = self.redact(system), self.redact(user)
        with self._lock:
            if len(self.records) >= self.max_records:
                self.dropped += 1
            else:
                self.records.append(rec)

    def record_schema_error(self, *, stage: str, agent: str, detail: str) -> None:
        """An agent returned an item of the wrong shape; the item was rejected."""
        with self._lock:
            if len(self.schema_errors) < self.max_records:
                self.schema_errors.append({"kind": "schema_error", "stage": stage or "", "agent": agent,
                                           "error": self.redact(detail)})
            self.schema_error_count += 1

    def failures(self) -> list[dict]:
        return [r for r in self.records if not r["ok"]]

    def models_used(self) -> dict:
        """The models that actually answered: {"provider:model": {"calls": n, "ok": n}} (a fallback shows up here)."""
        used: dict = {}
        for r in self.records:
            row = used.setdefault(f"{r['provider']}:{r['model']}", {"calls": 0, "ok": 0})
            row["calls"] += 1
            row["ok"] += 1 if r["ok"] else 0
        return used

    def summary(self) -> dict:
        calls = self.records
        return {"calls": len(calls), "failed": len(self.failures()), "dropped": self.dropped,
                "schema_errors": self.schema_error_count,
                "seconds": round(sum(r["latency_s"] for r in calls), 1)}

    def to_jsonl(self) -> str:
        with self._lock:
            lines = [json.dumps(r, ensure_ascii=False) for r in self.records + self.schema_errors]
        if self.dropped:
            lines.append(json.dumps({"note": f"{self.dropped} further calls not logged (cap {self.max_records})"}))
        return "\n".join(lines) + ("\n" if lines else "")
