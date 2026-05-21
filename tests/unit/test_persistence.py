"""Tests for UserSettings persistence — load, save, defaults, round-trip."""

from __future__ import annotations

from pathlib import Path


from lumi.ui.web.persistence import (
    AVAILABLE_SKILLS,
    UserSettings,
    load_settings,
    save_settings,
)


class TestDefaults:
    def test_default_lumi_name(self) -> None:
        s = UserSettings()
        assert s.lumi_name == "Lumi"

    def test_default_onboarding_not_complete(self) -> None:
        s = UserSettings()
        assert s.onboarding_complete is False
        assert s.onboarding_step == 1

    def test_default_all_skills_enabled(self) -> None:
        s = UserSettings()
        assert set(s.enabled_skills) == set(AVAILABLE_SKILLS)

    def test_default_permissions_off_except_wifi(self) -> None:
        s = UserSettings()
        assert s.wifi_skills_enabled is True
        assert s.active_window_enabled is False
        assert s.clipboard_enabled is False
        assert s.camera_enabled is False


class TestLoadSave:
    def test_load_returns_defaults_when_no_file(self, tmp_path: Path) -> None:
        s = load_settings(tmp_path)
        assert s.lumi_name == "Lumi"

    def test_round_trip(self, tmp_path: Path) -> None:
        s = UserSettings(lumi_name="Nova", mode="code", onboarding_complete=True)
        save_settings(tmp_path, s)
        loaded = load_settings(tmp_path)
        assert loaded.lumi_name == "Nova"
        assert loaded.mode == "code"
        assert loaded.onboarding_complete is True

    def test_creates_file(self, tmp_path: Path) -> None:
        save_settings(tmp_path, UserSettings())
        assert (tmp_path / "user_settings.json").exists()

    def test_load_returns_defaults_on_corrupt_file(self, tmp_path: Path) -> None:
        (tmp_path / "user_settings.json").write_text("not json")
        s = load_settings(tmp_path)
        assert s.lumi_name == "Lumi"

    def test_partial_update_preserves_other_fields(self, tmp_path: Path) -> None:
        s = UserSettings(lumi_name="Atlas", mode="focus")
        save_settings(tmp_path, s)
        loaded = load_settings(tmp_path)
        loaded.mode = "code"
        save_settings(tmp_path, loaded)
        final = load_settings(tmp_path)
        assert final.lumi_name == "Atlas"
        assert final.mode == "code"

    def test_skill_list_persisted(self, tmp_path: Path) -> None:
        s = UserSettings(enabled_skills=["weather", "timer"])
        save_settings(tmp_path, s)
        loaded = load_settings(tmp_path)
        assert loaded.enabled_skills == ["weather", "timer"]
