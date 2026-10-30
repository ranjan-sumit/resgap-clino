"""PR-23: the deployment can close the network (RESGAP_EGRESS), and the page loads nothing from a font service."""
import re
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

from utils import egress
from utils.provider_policy import ProviderNotAllowed, check_endpoint, check_provider, endpoint_problem, provider_allowed

ROOT = Path(__file__).resolve().parent.parent


# ── modes ───────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("value,expected", [("", "open"), ("open", "open"), ("MODELS", "models"), ("none", "none"),
                                            ("nnoe", "none"), ("false", "none"), ("0", "none")])
def test_the_mode_is_read_from_the_environment_and_an_unknown_value_closes_the_network(monkeypatch, value, expected):
    monkeypatch.setenv("RESGAP_EGRESS", value)
    assert egress.mode() == expected


def test_the_default_is_open_so_nothing_changes_for_existing_users(monkeypatch):
    monkeypatch.delenv("RESGAP_EGRESS", raising=False)
    assert egress.mode() == "open" and egress.scholarly_allowed() and egress.models_allowed()


# ── scholarly look-ups ───────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("mode", ["models", "none"])
def test_a_blocked_lookup_never_reaches_the_network_and_looks_like_a_failed_request(monkeypatch, mode):
    monkeypatch.setenv("RESGAP_EGRESS", mode)
    with patch("requests.get") as get:
        with pytest.raises(requests.RequestException) as e:
            egress.get("https://api.crossref.org/works?query=secret+title")
    get.assert_not_called()
    assert isinstance(e.value, egress.EgressBlocked) and "secret+title" not in str(e.value)      # the query is not echoed


def test_an_open_deployment_passes_the_call_through(monkeypatch):
    monkeypatch.setenv("RESGAP_EGRESS", "open")
    with patch("requests.get", return_value="ok") as get:
        assert egress.get("https://x.example", timeout=5) == "ok"
    get.assert_called_once_with("https://x.example", timeout=5)


@pytest.mark.parametrize("module", ["academic_search", "literature_scout", "reference_extractor"])
def test_no_scholarly_module_calls_requests_get_directly(module):
    src = (ROOT / "pipeline" / f"{module}.py").read_text(encoding="utf-8")
    assert not re.search(r"(?<![\w.])requests\.get\(", src), f"{module} bypasses utils.egress"


def test_every_remaining_direct_request_is_to_a_model_endpoint_that_the_policy_checks():
    direct = {}
    for path in list((ROOT / "pipeline").glob("*.py")) + list((ROOT / "utils").glob("*.py")) + [ROOT / "app.py"]:
        n = len(re.findall(r"(?<![\w.])requests\.(get|post|put|request)\(", path.read_text(encoding="utf-8")))
        if n:
            direct[path.name] = n
    assert direct == {"model_router.py": 1, "egress.py": 1}, direct       # fetch_models (policy-checked above it) and egress itself


def test_the_reference_pipeline_leaves_references_unresolved_when_look_ups_are_off(monkeypatch):
    monkeypatch.setenv("RESGAP_EGRESS", "none")
    from pipeline import reference_extractor as rx
    with patch("requests.get") as get:
        out = rx._crossref_citation_search("Smith J. A study of things. Nature 2020;1:1-2.")
    get.assert_not_called()
    assert not out


def test_literature_search_returns_nothing_when_look_ups_are_off(monkeypatch):
    monkeypatch.setenv("RESGAP_EGRESS", "models")
    from pipeline import literature_scout as ls
    with patch("requests.get") as get:
        rows, ok = ls._search_europepmc("cystic fibrosis")
    get.assert_not_called()
    assert rows == [] and ok is False


# ── models ───────────────────────────────────────────────────────────────────────────────────
def test_models_only_mode_still_allows_every_provider(monkeypatch):
    monkeypatch.setenv("RESGAP_EGRESS", "models")
    assert provider_allowed("gemini") and provider_allowed("custom")


def test_closed_mode_allows_only_the_custom_endpoint(monkeypatch):
    monkeypatch.setenv("RESGAP_EGRESS", "none")
    assert not provider_allowed("gemini") and not provider_allowed("nvidia") and provider_allowed("custom")
    with pytest.raises(ProviderNotAllowed, match="RESGAP_EGRESS=none"):
        check_provider("gemini")


def test_closed_mode_needs_the_endpoint_host_to_be_listed_unless_it_is_this_computer(monkeypatch):
    monkeypatch.setenv("RESGAP_EGRESS", "none")
    monkeypatch.delenv("RESGAP_ALLOWED_HOSTS", raising=False)
    assert "RESGAP_ALLOWED_HOSTS" in endpoint_problem("https://llm.corp.example/v1")
    assert endpoint_problem("http://localhost:11434/v1") is None
    monkeypatch.setenv("RESGAP_ALLOWED_HOSTS", "llm.corp.example")
    assert endpoint_problem("https://llm.corp.example/v1") is None
    with pytest.raises(ProviderNotAllowed):
        check_endpoint("https://other.example/v1")


def test_open_mode_leaves_the_existing_endpoint_rules_alone(monkeypatch):
    monkeypatch.setenv("RESGAP_EGRESS", "open")
    monkeypatch.delenv("RESGAP_ALLOWED_HOSTS", raising=False)
    assert endpoint_problem("https://llm.corp.example/v1") is None
    assert endpoint_problem("http://llm.corp.example/v1") is not None            # still https only


def test_model_list_is_not_fetched_from_a_hosted_provider_when_closed(monkeypatch):
    monkeypatch.setenv("RESGAP_EGRESS", "none")
    from utils.model_router import fetch_models
    with patch("utils.model_router.requests.get") as get:
        assert fetch_models("gemini", "k") == []
    get.assert_not_called()


# ── fonts ────────────────────────────────────────────────────────────────────────────────────
FONT_DIR = ROOT / "static" / "fonts"


def test_the_page_never_loads_a_stylesheet_script_or_font_from_another_site():
    pattern = re.compile(r"(?i)@import\s+url\(\s*['\"]?https?:|<link[^>]+href=['\"]https?:|<script[^>]+src=['\"]?https?:|url\(\s*['\"]?https?://|googleapis|gstatic")
    offenders = []
    for path in [ROOT / "app.py", *sorted((ROOT / "ui").glob("*.py")), ROOT / "utils" / "export.py", *sorted(FONT_DIR.glob("*.css"))]:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.name}:{n}")
    assert offenders == []


def test_every_font_the_stylesheet_names_is_declared_and_its_file_exists():
    css = (FONT_DIR / "fonts.css").read_text(encoding="utf-8")
    files = re.findall(r"url\(app/static/fonts/([^)]+)\)", css)
    assert len(files) >= 6 and all((FONT_DIR / f).is_file() and (FONT_DIR / f).stat().st_size > 5000 for f in files)
    declared = set(re.findall(r"font-family: '([^']+)'", css))
    assert {"DM Sans", "DM Mono", "DM Serif Display", "Inter"} <= declared
    theme = (ROOT / "ui" / "theme.py").read_text(encoding="utf-8")
    used = set(re.findall(r"font-family:\s*'([^']+)'", theme))
    assert {u for u in used if u.startswith("DM ")} <= declared


def test_woff2_files_are_real_font_files():
    for f in FONT_DIR.glob("*.woff2"):
        assert f.read_bytes()[:4] == b"wOF2", f.name


def test_streamlit_serves_the_static_folder_and_the_image_keeps_it():
    assert re.search(r"(?m)^enableStaticServing\s*=\s*true", (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "static" not in [ln.strip().rstrip("/") for ln in ignore]


def test_the_font_licence_notice_is_shipped_with_the_fonts():
    text = (FONT_DIR / "LICENSES.md").read_text(encoding="utf-8")
    assert "SIL Open Font License" in text and "Inter" in text and "DM Sans" in text


def test_the_theme_injects_the_font_rules():
    from ui import theme
    css = theme.font_css()
    assert css.startswith("<style>") and "@font-face" in css and "app/static/fonts/" in css
