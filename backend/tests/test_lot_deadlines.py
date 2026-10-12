from datetime import UTC, datetime, timedelta

from app.api.lots import _deadline_metadata


def test_expired_deadline_is_never_urgent():
    now = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)

    days_left, is_urgent, label = _deadline_metadata(
        now - timedelta(days=5),
        now=now,
    )

    assert days_left is None
    assert is_urgent is False
    assert label.startswith("приём завершён")


def test_future_deadline_can_be_urgent():
    now = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)

    days_left, is_urgent, _ = _deadline_metadata(
        now + timedelta(hours=30),
        now=now,
    )

    assert days_left == 2
    assert is_urgent is True
