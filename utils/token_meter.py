"""
Token usage accounting (Clinova Phase 4, Epic 4.3 token instrumentation,
2026-08-24). Before this, token_usage was structurally discarded, not
merely unrecorded: utils/azure_client.py never requested
stream_options={"include_usage": True}, and _collect_stream() skipped
exactly the terminal usage-bearing chunk via its
`if not chunk.choices: continue` check. Both are now fixed (see
azure_client.py's _collect_stream()/chat()) -- this module is where the
captured usage actually accumulates.

by_agent is populated only when a caller explicitly attributes a call to
one of pipeline/agent_config.py's real roles -- never inferred or
guessed, so an omitted role means exactly that: unattributed, not
"assigned to whichever agent seemed likely."
"""

TOKEN_METER_VERSION = 1


class TokenMeter:
    def __init__(self):
        self._records: list[dict] = []

    def record(self, model: str, usage: dict, stage: str = None, agent: str = None) -> None:
        """`usage` is the {"prompt_tokens", "completion_tokens",
        "total_tokens"} dict azure_client.py's _collect_stream() fills in.
        A call whose usage capture failed (provider didn't support
        stream_options, or the terminal chunk never arrived) is simply
        never recorded here -- not recorded as zero, which would be a
        fabricated number."""
        if not usage or usage.get("total_tokens") is None:
            return
        self._records.append({
            "stage": stage, "agent": agent, "model": model,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
        })

    def to_manifest_dict(self) -> dict | None:
        """Returns {total, by_stage, by_agent, by_model, n_calls_recorded}
        for run_manifests.token_usage, or None if nothing was ever
        recorded (honest -- matches the pre-instrumentation convention of
        leaving the field NULL rather than writing a fabricated {total: 0,
        ...} for a run where usage capture never worked at all, e.g. every
        call went through a provider that rejects stream_options)."""
        if not self._records:
            return None

        def _bucket(key: str) -> dict:
            totals: dict = {}
            for r in self._records:
                k = r.get(key)
                if k is None:
                    continue
                totals[k] = totals.get(k, 0) + (r["total_tokens"] or 0)
            return totals

        total = sum(r["total_tokens"] or 0 for r in self._records)
        return {
            "token_meter_version": TOKEN_METER_VERSION,
            "total": total,
            "by_stage": _bucket("stage"),
            "by_agent": _bucket("agent"),
            "by_model": _bucket("model"),
            "n_calls_recorded": len(self._records),
        }
