"""Integration tests for the Lumi web dashboard routes.

Requires the [web] extra: uv pip install -e ".[web]"
Skipped automatically if fastapi is not installed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("jinja2")

from fastapi.testclient import TestClient  # noqa: E402

from lumi.ui.web.app import create_app  # noqa: E402
from lumi.ui.web.persistence import UserSettings, save_settings  # noqa: E402


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path)
    return TestClient(app, follow_redirects=True)


@pytest.fixture
def onboarded_client(tmp_path: Path) -> TestClient:
    s = UserSettings(onboarding_complete=True, lumi_name="Nova")
    save_settings(tmp_path, s)
    app = create_app(tmp_path)
    return TestClient(app, follow_redirects=True)


class TestDashboard:
    def test_redirects_to_onboarding_when_not_complete(self, client: TestClient) -> None:
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Step 1" in resp.text or "Welcome" in resp.text or "onboarding" in resp.url

    def test_shows_dashboard_when_onboarding_complete(self, onboarded_client: TestClient) -> None:
        resp = onboarded_client.get("/")
        assert resp.status_code == 200
        assert "Nova" in resp.text


class TestOnboarding:
    def test_step_1_renders(self, client: TestClient) -> None:
        resp = client.get("/onboarding/1")
        assert resp.status_code == 200
        assert "Lumi" in resp.text

    def test_step_3_saves_name(self, tmp_path: Path) -> None:
        app = create_app(tmp_path)
        c = TestClient(app, follow_redirects=True)
        resp = c.post("/onboarding/3", data={"lumi_name": "Atlas"})
        assert resp.status_code == 200
        from lumi.ui.web.persistence import load_settings
        s = load_settings(tmp_path)
        assert s.lumi_name == "Atlas"

    def test_step_4_skip_advances(self, tmp_path: Path) -> None:
        app = create_app(tmp_path)
        c = TestClient(app, follow_redirects=True)
        resp = c.post("/onboarding/4/skip")
        assert resp.status_code == 200
        from lumi.ui.web.persistence import load_settings
        s = load_settings(tmp_path)
        assert s.onboarding_step == 5

    def test_step_5_saves_voice(self, tmp_path: Path) -> None:
        app = create_app(tmp_path)
        c = TestClient(app, follow_redirects=True)
        c.post("/onboarding/5", data={"piper_voice": "en_GB-jenny-diphone"})
        from lumi.ui.web.persistence import load_settings
        s = load_settings(tmp_path)
        assert s.piper_voice == "en_GB-jenny-diphone"

    def test_step_9_marks_complete(self, tmp_path: Path) -> None:
        app = create_app(tmp_path)
        c = TestClient(app, follow_redirects=True)
        c.post("/onboarding/9", data={"owner_name": "Alex"})
        from lumi.ui.web.persistence import load_settings
        s = load_settings(tmp_path)
        assert s.onboarding_complete is True
        assert s.owner_name == "Alex"

    def test_out_of_range_step_redirects(self, client: TestClient) -> None:
        resp = client.get("/onboarding/99")
        assert resp.status_code == 200


class TestSettings:
    def test_personality_page_renders(self, onboarded_client: TestClient) -> None:
        resp = onboarded_client.get("/settings/personality")
        assert resp.status_code == 200
        assert "system prompt" in resp.text.lower()

    def test_personality_saves_override(self, tmp_path: Path) -> None:
        s = UserSettings(onboarding_complete=True)
        save_settings(tmp_path, s)
        c = TestClient(create_app(tmp_path), follow_redirects=True)
        c.post("/settings/personality", data={"system_prompt_override": "Be brief."})
        from lumi.ui.web.persistence import load_settings
        assert load_settings(tmp_path).system_prompt_override == "Be brief."

    def test_modes_page_renders(self, onboarded_client: TestClient) -> None:
        resp = onboarded_client.get("/settings/modes")
        assert resp.status_code == 200
        assert "focus" in resp.text.lower()

    def test_data_page_renders(self, onboarded_client: TestClient) -> None:
        resp = onboarded_client.get("/settings/data")
        assert resp.status_code == 200
        assert "permissions" in resp.text.lower() or "privacy" in resp.text.lower()

    def test_data_saves_permissions(self, tmp_path: Path) -> None:
        s = UserSettings(onboarding_complete=True)
        save_settings(tmp_path, s)
        c = TestClient(create_app(tmp_path), follow_redirects=True)
        c.post("/settings/data", data={"clipboard": "on", "wifi_skills": "on"})
        from lumi.ui.web.persistence import load_settings
        loaded = load_settings(tmp_path)
        assert loaded.clipboard_enabled is True
        assert loaded.active_window_enabled is False


class TestSkills:
    def test_skills_page_renders(self, onboarded_client: TestClient) -> None:
        resp = onboarded_client.get("/skills")
        assert resp.status_code == 200
        assert "weather" in resp.text.lower()

    def test_toggle_disables_skill(self, tmp_path: Path) -> None:
        s = UserSettings(onboarding_complete=True)
        save_settings(tmp_path, s)
        c = TestClient(create_app(tmp_path), follow_redirects=False)
        resp = c.post("/skills/weather/toggle")
        assert resp.status_code == 200
        from lumi.ui.web.persistence import load_settings
        assert "weather" not in load_settings(tmp_path).enabled_skills

    def test_toggle_re_enables_skill(self, tmp_path: Path) -> None:
        s = UserSettings(onboarding_complete=True, enabled_skills=["timer"])
        save_settings(tmp_path, s)
        c = TestClient(create_app(tmp_path), follow_redirects=False)
        c.post("/skills/weather/toggle")
        from lumi.ui.web.persistence import load_settings
        assert "weather" in load_settings(tmp_path).enabled_skills

    def test_audit_log_rows_partial(self, onboarded_client: TestClient) -> None:
        resp = onboarded_client.get("/skills/audit-log/rows")
        assert resp.status_code == 200
