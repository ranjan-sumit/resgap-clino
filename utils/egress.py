"""How far this deployment may reach beyond its own network.

The app makes two kinds of outbound call: to a model provider (paper text goes out) and to scholarly look-up services
(Crossref, OpenAlex, Semantic Scholar, PubMed / Europe PMC, arXiv, Unpaywall; only titles, DOIs and search words go out).
One environment variable sets what is allowed:

    RESGAP_EGRESS=open     (default) both kinds.
    RESGAP_EGRESS=models   model providers only; no scholarly look-ups.
    RESGAP_EGRESS=none     nothing leaves the network except a custom model endpoint on this computer or on a host listed in
                           RESGAP_ALLOWED_HOSTS (see utils/provider_policy.py).

Any other value is treated as `none`, so a typo cannot open the network. A blocked look-up raises EgressBlocked, which is a
requests exception, so every caller treats it like a service that did not answer: the references are left unresolved and the
trace says so.
"""
from __future__ import annotations

import os

import requests

MODES = ("open", "models", "none")


class EgressBlocked(requests.exceptions.RequestException):
    """This deployment does not allow that outbound call."""


def mode() -> str:
    raw = os.getenv("RESGAP_EGRESS", "").strip().lower()
    if not raw:
        return "open"
    return raw if raw in MODES else "none"


def scholarly_allowed() -> bool:
    return mode() == "open"


def models_allowed() -> bool:
    return mode() in ("open", "models")


def require_scholarly(url: str = "") -> None:
    if not scholarly_allowed():
        raise EgressBlocked(f"Outbound look-ups are switched off on this deployment (RESGAP_EGRESS={mode()}): {url.split('?')[0]}")


def get(url: str, **kwargs):
    """requests.get for a scholarly look-up, refused when the deployment does not allow them."""
    require_scholarly(url)
    return requests.get(url, **kwargs)


def describe() -> str:
    return {"open": "Open: model providers and reference look-ups are reachable.",
            "models": "Models only: reference and literature look-ups are switched off.",
            "none": "Closed: nothing leaves the network except an approved model endpoint."}[mode()]
