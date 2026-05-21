"""Tests for runtime.session.build_cloud_bridge — the shared helper that
keeps the voice loop and the web chat from drifting on cloud-mode wiring."""

from __future__ import annotations

from unittest.mock import patch

from lumi.runtime.session import build_cloud_bridge


class _FakeUser:
    """Stand-in for UserSettings — only the fields the helper reads."""

    def __init__(
        self,
        *,
        openclaw_enabled: bool = True,
        cloud_llm_api_key_set: bool = False,
        cloud_llm_provider: str = "",
        owner_name: str = "",
    ) -> None:
        self.openclaw_enabled = openclaw_enabled
        self.cloud_llm_api_key_set = cloud_llm_api_key_set
        self.cloud_llm_provider = cloud_llm_provider
        self.owner_name = owner_name


def test_returns_no_bridge_when_openclaw_disabled() -> None:
    """System-level openclaw off → router falls straight through to LLM."""
    user = _FakeUser(cloud_llm_api_key_set=True, cloud_llm_provider="anthropic")
    bridge, pseudo, mode = build_cloud_bridge(user, openclaw_enabled=False)
    assert bridge is None
    assert pseudo is None
    assert mode == "ollama"


def test_v1_hybrid_mode_when_no_cloud_key() -> None:
    """OpenClaw on + no cloud key → ollama mode, no pseudonymizer."""
    user = _FakeUser()         # defaults: no cloud key
    with patch("lumi.runtime.session.OpenClawBridge") as fake_bridge:
        bridge, pseudo, mode = build_cloud_bridge(user, openclaw_enabled=True)

    assert mode == "ollama"
    assert pseudo is None
    fake_bridge.assert_called_once()
    kwargs = fake_bridge.call_args.kwargs
    assert kwargs["runtime_mode"] == "ollama"
    assert kwargs["pseudonymizer"] is None


def test_cloud_mode_attaches_pseudonymizer_seeded_with_owner_name() -> None:
    """When all three cloud signals line up, we build a Pseudonymizer
    pre-seeded with the owner's name from onboarding."""
    user = _FakeUser(
        cloud_llm_api_key_set=True,
        cloud_llm_provider="anthropic",
        owner_name="Abhishek",
    )
    with (
        patch("lumi.runtime.session.OpenClawBridge") as fake_bridge,
        patch("lumi.runtime.session.ensure_config_perms") as fake_remediate,
    ):
        bridge, pseudo, mode = build_cloud_bridge(user, openclaw_enabled=True)

    assert mode == "openclaw_cloud"
    assert pseudo is not None
    assert "Abhishek" in pseudo.extra_names
    # The legacy-config remediation runs *before* any cloud activity.
    fake_remediate.assert_called_once()
    kwargs = fake_bridge.call_args.kwargs
    assert kwargs["runtime_mode"] == "openclaw_cloud"
    assert kwargs["pseudonymizer"] is pseudo


def test_cloud_mode_with_no_owner_name_still_produces_pseudonymizer() -> None:
    """Even if onboarding skipped the name capture, regex patterns still
    mask email/phone/etc. — the pseudonymizer must exist."""
    user = _FakeUser(
        cloud_llm_api_key_set=True, cloud_llm_provider="openai", owner_name="",
    )
    with (
        patch("lumi.runtime.session.OpenClawBridge"),
        patch("lumi.runtime.session.ensure_config_perms"),
    ):
        _bridge, pseudo, mode = build_cloud_bridge(user, openclaw_enabled=True)

    assert mode == "openclaw_cloud"
    assert pseudo is not None
    assert pseudo.extra_names == []


def test_partial_cloud_config_does_not_activate_cloud_mode() -> None:
    """Having a provider but no key (or vice versa) must NOT activate cloud
    mode — that would risk sending PII to a misconfigured destination."""
    # Provider set, key flag false
    u1 = _FakeUser(cloud_llm_api_key_set=False, cloud_llm_provider="anthropic")
    # Key flag true, provider blank
    u2 = _FakeUser(cloud_llm_api_key_set=True, cloud_llm_provider="")

    with patch("lumi.runtime.session.OpenClawBridge"):
        _b1, p1, m1 = build_cloud_bridge(u1, openclaw_enabled=True)
        _b2, p2, m2 = build_cloud_bridge(u2, openclaw_enabled=True)

    assert m1 == "ollama" and p1 is None
    assert m2 == "ollama" and p2 is None
