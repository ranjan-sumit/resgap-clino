# Audit 22e: model providers (OpenAI, Groq, custom endpoint, and the built-in list)

**What could be run live:** Gemini and NVIDIA (their keys are in `.env`). **What could not:** OpenAI, Groq and Qwen, because there
are no keys for them. For those, and for the custom endpoint, the real client and the real OpenAI SDK were run against a local
OpenAI-compatible server written for the audit (`tests/test_custom_endpoint.py`), including one that behaves like OpenAI's
stricter newer models. That shows how the client behaves; it does not show that a given provider's current models accept our
requests, so the three providers without keys stay marked "not verified live". Dated 2026-10-23.

## Findings and fixes

| # | Finding | Effect | Fix |
|---|---|---|---|
| 1 | **Two of NVIDIA's four listed models are retired (HTTP 410 Gone):** `moonshotai/kimi-k3` and `deepseek-ai/deepseek-v4-flash-0731`, both gone from NVIDIA's own model list. kimi-k3 was also NVIDIA's built-in fallback. The default `openai/gpt-oss-20b` timed out at 181 s; only `nemotron-3.5-super-vl` answered (54 s). | A fallback that could never answer, and suggested models that fail. | Retired models removed; NVIDIA has no built-in fallback. Only models seen answering stay in the list. |
| 2 | **The SDK silently retried every timeout twice.** A 60 s limit failed after 182 s; every timeout in the app cost three times what was asked for, on top of the app's own retries. | Slow failures, and two retry layers fighting each other. | The SDK's retries are off (`max_retries=0`); the app's own retry, which honours the provider's wait time, is the only one. Verified against a hanging server: one 2 s attempt, not three. |
| 3 | `gemini-3.7-flash` timed out on a one-word request at 125 s and 182 s. | Suggested in the list, unusable. | Left out of the suggested list; still selectable if "Refresh model list" shows it. |
| 4 | **OpenAI's newer models refuse `max_tokens` and any non-default `temperature` or `top_p`** (HTTP 400, "use `max_completion_tokens`", "only the default (1) is supported"). Every call this app makes sends all three. | OpenAI as a provider would fail on every call. | The client learns what a model refuses from its own error, retries once with the right parameters, and remembers it per provider and model. Nothing changes for providers that accept them. Tested end to end against the strict server (3 requests the first time, 1 afterwards). **Not confirmed against OpenAI itself.** |
| 5 | **The custom endpoint accepted any address.** The key and the paper text would go to `http://` addresses (in clear), to addresses with a user name and password in them, and to link-local addresses including the cloud metadata service (169.254.169.254). On a hosted copy anyone with Settings access could point the server at its own internal network. | A credential and data leak, and a server-side request forgery risk. | Addresses are checked wherever they are used (building the client, listing models, the test button, Settings): https required (plain http only for this computer, e.g. a local Ollama), no credentials in the address, no link-local or metadata addresses. A refused address is explained in Settings and never receives the key. |
| 6 | Any provider could be selected by whoever opens Settings. | In a controlled deployment the operator, not the user, decides where paper text may go. | `RESGAP_ALLOWED_PROVIDERS` (e.g. `gemini,custom`) and `RESGAP_ALLOWED_HOSTS` (host names, `.suffix` allowed) limit the providers offered, the models listed and the clients built. The picker offers only the allowed ones. |
| 7 | A retired model, a model the key cannot use, and a rejected key all showed as raw error text. | Hard to act on. | "The provider has retired this model (HTTP 410). Choose another in Settings > Models; Refresh model list shows what your key can use." and similar for 404 and 401. |

## Still open

- OpenAI, Groq and Qwen model names in the list (`gpt-5.6-*`, `qwen3.8-max`, ...) cannot be checked without keys; use "Refresh model list" and "Test models" with a real key before relying on them.
- The host check does not resolve names: a host name that points at a link-local address is not caught. In a controlled deployment use `RESGAP_ALLOWED_HOSTS`.
- Provider terms (retention, training on prompts, region) are not something the app can check; they are part of the deployment decision.
- Prices are only known for models listed in `data/model_prices.json`; others show no cost estimate.
- NVIDIA's account was slow throughout the audit (54 s to 181 s per call), so the app's default model on that provider is poor right now; Gemini answered in about a second.
