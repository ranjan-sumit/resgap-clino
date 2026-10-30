"""PR-22h: the container files, checked as text (no Docker needed), plus a real build-and-run test that runs only where Docker works."""
import fnmatch
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
yaml = pytest.importorskip("yaml")
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
DEV = yaml.safe_load((ROOT / "docker-compose.dev.yml").read_text(encoding="utf-8"))
APP = COMPOSE["services"]["app"]
LOCK = (ROOT / "requirements-runtime.lock").read_text(encoding="utf-8")


def _lines(text):
    return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]


# ── the image ───────────────────────────────────────────────────────────────────────────────
def test_the_image_runs_as_an_ordinary_user_after_everything_is_installed():
    instr = [ln.split()[0] for ln in _lines(DOCKERFILE)]
    assert "USER" in instr and instr.index("USER") > max(i for i, k in enumerate(instr) if k in ("RUN", "COPY"))
    user_line = next(ln for ln in _lines(DOCKERFILE) if ln.startswith("USER"))
    assert "root" not in user_line and user_line.split()[1] == "app"


def test_dependencies_come_from_the_hashed_runtime_lock_not_the_loose_requirements():
    assert "COPY requirements-runtime.lock" in DOCKERFILE
    assert "pip install --require-hashes -r requirements-runtime.lock" in DOCKERFILE
    assert "requirements.txt" not in DOCKERFILE and "requirements-dev" not in DOCKERFILE


def test_data_lives_in_a_volume_and_every_writable_setting_points_there():
    for var in ("RESGAP_DB_PATH", "RESGAP_PROJECTS_DIR", "RESGAP_BACKUP_DIR"):
        assert re.search(rf"{var}=/data/", DOCKERFILE)
    assert 'VOLUME ["/data"]' in DOCKERFILE


def test_the_image_has_a_health_check_telemetry_off_and_no_secrets():
    assert "HEALTHCHECK" in DOCKERFILE and "/_stcore/health" in DOCKERFILE
    assert "STREAMLIT_BROWSER_GATHER_USAGE_STATS=false" in DOCKERFILE and "STREAMLIT_SERVER_HEADLESS=true" in DOCKERFILE
    assert not re.search(r"(?i)(api_key|secret|password|token)\s*=\s*\S", DOCKERFILE)
    for ln in _lines(DOCKERFILE):                                           # comments are skipped by _lines
        assert not (ln.startswith(("COPY", "ADD")) and re.search(r"(^|\s)\.env\b", ln.replace("COPY . .", ""))), ln
        assert not (ln.startswith("ENV") and ".env" in ln), ln


def test_cross_site_request_protection_and_cors_are_not_switched_off_anywhere():
    for name in ("Dockerfile", "docker-compose.yml", "docker-compose.dev.yml"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert not re.search(r"enableXsrfProtection[= ]+false", text, re.I), name
        assert not re.search(r"enableCORS[= ]+false", text, re.I), name


# ── how it is run ───────────────────────────────────────────────────────────────────────────
def test_the_port_is_published_on_this_machine_only():
    assert APP["ports"] == ["127.0.0.1:8501:8501"]


def test_the_container_is_read_only_unprivileged_and_limited():
    assert APP["read_only"] is True and "ALL" in APP["cap_drop"]
    assert "no-new-privileges:true" in APP["security_opt"]
    assert APP["mem_limit"] and APP["pids_limit"]
    assert "/tmp" in APP["tmpfs"]


def test_the_source_tree_is_not_mounted_in_the_base_file_but_is_in_the_dev_override():
    assert not any(str(v).startswith((".:", "./")) for v in APP.get("volumes", []))
    assert any(str(v).startswith("data:/data") for v in APP["volumes"]) and "data" in COMPOSE["volumes"]
    assert any(str(v).startswith(".:/app") for v in DEV["services"]["app"]["volumes"])


def test_the_old_api_image_and_the_host_specific_copy_are_gone():
    assert not (ROOT / "Dockerfile.api").exists() and not (ROOT / "docker-compose.compat.yml").exists()


def test_the_compose_file_has_no_top_level_name_that_older_compose_versions_reject():
    assert "name" not in COMPOSE


# ── the dependency lock ─────────────────────────────────────────────────────────────────────
def _packages(lock):
    return re.findall(r"^([A-Za-z0-9_.\-]+)==([^\s\\]+)", lock, re.M)


def test_every_package_in_the_runtime_lock_is_pinned_and_hashed():
    names = _packages(LOCK)
    assert len(names) >= 40
    blocks = re.split(r"\n(?=[A-Za-z0-9_.\-]+==)", LOCK)
    unhashed = [b.split("==")[0] for b in blocks if "==" in b.split("\n")[0] and "--hash=sha256:" not in b]
    assert unhashed == []


def test_the_runtime_lock_has_no_development_tools_and_no_untested_pdf_stack():
    names = {n.lower() for n, _ in _packages(LOCK)}
    assert not names & {"pytest", "playwright", "pip-audit"}
    assert not names & {"onnxruntime", "pymupdf-layout", "pymupdf4llm"}              # PyMuPDF 2.x extras
    assert dict((n.lower(), v) for n, v in _packages(LOCK))["pymupdf"].startswith("1.")


def test_every_top_level_requirement_is_in_the_lock_and_pymupdf_is_held_below_2():
    names = {n.lower().replace("_", "-") for n, _ in _packages(LOCK)}
    req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    wanted = [re.split(r"[<>=!~\[ ]", ln.strip())[0].lower() for ln in req.splitlines()
              if ln.strip() and not ln.strip().startswith(("#", "-"))]
    assert wanted and all(w.replace("_", "-") in names for w in wanted), [w for w in wanted if w not in names]
    assert re.search(r"(?i)^PyMuPDF>=1\.24\.0,<2", req, re.M)


# ── what goes into the image ────────────────────────────────────────────────────────────────
def _ignored(path: str) -> bool:
    patterns = [ln.strip() for ln in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.startswith("#")]
    ignored = False
    for pat in patterns:
        negate = pat.startswith("!")
        pat = pat.lstrip("!").rstrip("/")
        hit = any(fnmatch.fnmatch(part, pat) for part in [path, *path.split("/")]) or fnmatch.fnmatch(path, pat + "/*")
        if hit:
            ignored = not negate
    return ignored


@pytest.mark.parametrize("path", ["app.py", "domain_config.py", "pipeline/run_pipeline.py", "utils/database.py", "ui/theme.py",
                                  "migrations/0001_init.sql" if (ROOT / "migrations" / "0001_init.sql").exists() else "migrations",
                                  "packages/__init__.py", ".streamlit/config.toml", "requirements-runtime.lock",
                                  "scripts/backup.py"])
def test_what_the_app_needs_is_not_excluded_from_the_image(path):
    assert not _ignored(path), path


@pytest.mark.parametrize("path", [".env", ".env.local", "data/run_history.db", "run_history.db", ".git/config", "tests/conftest.py",
                                  "docs/audit-22h.md", "backup.zip", "evals/benchmarks/x.json"])
def test_secrets_data_tests_and_notes_are_kept_out_of_the_image(path):
    assert _ignored(path), path


def test_the_env_example_is_still_available_to_copy():
    assert not _ignored(".env.example")


def test_the_devcontainer_no_longer_upgrades_the_system_or_installs_unpinned_streamlit():
    text = (ROOT / ".devcontainer" / "devcontainer.json").read_text(encoding="utf-8")
    assert "apt upgrade" not in text and "pip3 install --user streamlit" not in text


# ── the real thing, where Docker works ──────────────────────────────────────────────────────
def _docker_works():
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], capture_output=True, timeout=30).returncode == 0


@pytest.mark.slow
@pytest.mark.skipif(not _docker_works(), reason="no running Docker daemon")
def test_the_image_builds_starts_healthy_runs_as_a_non_root_user_and_writes_only_to_its_volume():
    tag, name = "clinova-test:ci", "clinova-test-ci"

    def run(*args, **kw):
        return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=kw.pop("timeout", 600), **kw)
    assert run("build", "-t", tag, str(ROOT), timeout=1500).returncode == 0
    run("rm", "-f", name)
    try:
        up = run("run", "-d", "--name", name, "--read-only", "--tmpfs", "/tmp", "--tmpfs", "/home/app", "--cap-drop", "ALL",
                 "--security-opt", "no-new-privileges:true", "-v", f"{name}-data:/data", tag)
        assert up.returncode == 0, up.stderr
        healthy = False
        for _ in range(60):
            status = run("inspect", "--format", "{{.State.Health.Status}}", name).stdout.strip()
            if status == "healthy":
                healthy = True
                break
            time.sleep(3)
        assert healthy, run("logs", name).stdout[-2000:]
        assert run("exec", name, "id", "-u").stdout.strip() == "10001"
        assert run("exec", name, "sh", "-c", "touch /app/x").returncode != 0              # the code is read-only
        assert run("exec", name, "sh", "-c", "touch /data/x && rm /data/x").returncode == 0  # the volume is writable
        assert run("exec", name, "python", "-c",
                   "import app_check" if False else "import pipeline.run_pipeline, utils.database, ui.theme").returncode == 0
    finally:
        run("rm", "-f", name)
        run("volume", "rm", "-f", f"{name}-data")
