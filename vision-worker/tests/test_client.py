"""Tests for the fire-and-forget gesture/presence HTTP push client.

Mocks httpx.post and waits on the client's own single-worker executor
(via .shutdown(wait=True) on a throwaway copy is overkill — instead we
just submit through the real module-level executor and poll its queue
being empty, matching how a fire-and-forget design is normally tested:
we care that the right call happened, not exact timing).
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
from lumi_vision_worker import client


def _wait_for_executor_idle() -> None:
    # The module-level executor is a single worker; submit a no-op and
    # wait for it, which guarantees everything submitted before it has
    # already completed (single-worker FIFO).
    client._executor.submit(lambda: None).result(timeout=2.0)


def test_push_gesture_posts_type_field() -> None:
    with patch("httpx.post") as mock_post:
        client.push_gesture("wave", base_url="http://127.0.0.1:8080")
        _wait_for_executor_idle()
    mock_post.assert_called_once_with(
        "http://127.0.0.1:8080/api/gesture", data={"type": "wave"}, timeout=1.5,
    )


def test_push_presence_posts_present_field() -> None:
    with patch("httpx.post") as mock_post:
        client.push_presence(True, base_url="http://127.0.0.1:8080")
        _wait_for_executor_idle()
    mock_post.assert_called_once_with(
        "http://127.0.0.1:8080/api/presence", data={"present": "True"}, timeout=1.5,
    )


def test_push_gesture_swallows_connection_errors() -> None:
    """A dead/unreachable web server must not raise into the caller —
    same fire-and-forget philosophy as device_display_client.py."""
    with patch("httpx.post", side_effect=httpx.ConnectError("refused")):
        client.push_gesture("thumbs_up", base_url="http://127.0.0.1:8080")
        _wait_for_executor_idle()  # must not raise


def test_base_url_trailing_slash_is_stripped() -> None:
    with patch("httpx.post") as mock_post:
        client.push_gesture("fist", base_url="http://127.0.0.1:8080/")
        _wait_for_executor_idle()
    args, _kwargs = mock_post.call_args
    assert args[0] == "http://127.0.0.1:8080/api/gesture"
