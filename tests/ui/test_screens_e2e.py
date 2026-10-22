import pytest

from tests.ui.harness import running_app, screenshot_all

pytestmark = pytest.mark.e2e


def test_home_renders_at_three_viewports(tmp_path):
    with running_app(tmp_path) as url:
        shots = screenshot_all(url, "home")
    assert len(shots) == 3 and all(p.stat().st_size > 5000 for p in shots)
