"""The heartbeat asks for an automatic screenshot only when one is due."""
from datetime import datetime, timedelta, timezone

from app.api.v1.devices.devices import auto_screenshot_due

NOW = datetime(2026, 10, 13, 10, 0, tzinfo=timezone.utc)


def test_due_when_device_has_never_been_captured():
    assert auto_screenshot_due(None, NOW, 60)


def test_due_one_minute_after_the_last_capture():
    assert auto_screenshot_due(NOW - timedelta(seconds=60), NOW, 60)


def test_due_when_capture_landed_a_few_seconds_late():
    # previous request went out 60s ago but the capture only landed 55s ago
    assert auto_screenshot_due(NOW - timedelta(seconds=55), NOW, 60)


def test_not_due_right_after_a_capture():
    assert not auto_screenshot_due(NOW - timedelta(seconds=20), NOW, 60)
