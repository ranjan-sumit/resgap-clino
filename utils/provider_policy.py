"""Which model providers and endpoints this deployment may talk to.

Every model call sends paper text to a provider, so in a controlled environment the set of providers is a decision for the
operator, not for whoever types in Settings. Two environment variables set it:

    RESGAP_ALLOWED_PROVIDERS   comma list of provider keys, e.g. "gemini,custom". Unset: every built-in provider.
    RESGAP_ALLOWED_HOSTS       comma list of host names the custom endpoint may use, e.g. "llm.corp.example,.internal.example"
                               (a leading dot allows every sub-domain). Unset: any host that passes the checks below.

RESGAP_EGRESS (utils/egress.py) can close the network further: with "none" only the custom endpoint is allowed, and only on this
computer or a host named in RESGAP_ALLOWED_HOSTS.

A custom endpoint receives the API key and the paper text, so its address is checked whatever the settings: https is required
(plain http only for the machine itself, e.g. a local Ollama), a user name or password in the address is refused, and
link-local addresses, which include the cloud metadata service at 169.254.169.254, are refused.
"""
from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlparse

from utils import egress

_LOOPBACK = {"localhost", "127.0.0.1", "::1"}
_METADATA_HOSTS = {"metadata.google.internal", "metadata", "instance-data"}


class ProviderNotAllowed(ValueError):
    """The deployment's policy does not allow this provider or endpoint."""


def _csv(name: str) -> set[str] | None:
    raw = os.getenv(name, "").strip()
    return {p.strip().lower() for p in raw.split(",") if p.strip()} if raw else None


def provider_allowed(provider: str) -> bool:
    if egress.mode() == "none" and provider.lower() != "custom":
        return False                                # a closed network reaches no hosted provider (RESGAP_EGRESS=none)
    allowed = _csv("RESGAP_ALLOWED_PROVIDERS")
    return allowed is None or provider.lower() in allowed


def check_provider(provider: str) -> None:
    if not provider_allowed(provider):
        if egress.mode() == "none" and provider.lower() != "custom":
            raise ProviderNotAllowed(f"The provider '{provider}' is a hosted service and this deployment allows no outbound "
                                     f"connections (RESGAP_EGRESS=none). Use the custom endpoint inside your network.")
        raise ProviderNotAllowed(f"The provider '{provider}' is not allowed on this deployment "
                                 f"(allowed: {', '.join(sorted(_csv('RESGAP_ALLOWED_PROVIDERS') or []))}).")


def _host_allowed(host: str) -> bool:
    hosts = _csv("RESGAP_ALLOWED_HOSTS")
    if hosts is None:
        return True
    host = host.lower()
    return any(host == h or (h.startswith(".") and host.endswith(h)) for h in hosts)


def endpoint_problem(url: str) -> str | None:
    """Why a custom endpoint address is refused, or None when it may be used."""
    url = (url or "").strip()
    if not url:
        return "The custom endpoint needs a base URL."
    try:
        parts = urlparse(url)
        host = (parts.hostname or "").lower()
    except ValueError:
        return "That is not a valid address."
    if parts.scheme not in ("https", "http") or not host:
        return "Use a full address starting with https://."
    if parts.username or parts.password:
        return "Remove the user name or password from the address; put the key in the key field."
    if parts.scheme == "http" and host not in _LOOPBACK:
        return "Use https:// (plain http is allowed only for this computer, e.g. http://localhost:11434/v1)."
    if host in _METADATA_HOSTS:
        return "That address is a cloud metadata service, not a model endpoint."
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            return "That address (link-local or reserved, which includes the cloud metadata service) is not allowed."
    except ValueError:
        pass                                    # a host name, not an address
    if not _host_allowed(host):
        return f"The host '{host}' is not on this deployment's list of allowed hosts."
    if egress.mode() == "none" and host not in _LOOPBACK and _csv("RESGAP_ALLOWED_HOSTS") is None:
        return "This deployment allows no outbound connections (RESGAP_EGRESS=none): list the endpoint's host in RESGAP_ALLOWED_HOSTS."
    return None


def check_endpoint(url: str) -> None:
    problem = endpoint_problem(url)
    if problem:
        raise ProviderNotAllowed(problem)
