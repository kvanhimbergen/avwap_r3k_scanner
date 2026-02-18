from __future__ import annotations

import json
import time

import pytest

from analytics.schwab_token_health import (
    REFRESH_TOKEN_MAX_AGE_DAYS,
    TokenHealthStatus,
    check_token_health,
)


class TestCheckTokenHealth:
    def test_missing_file(self, tmp_path):
        result = check_token_health(str(tmp_path / "nonexistent.json"))
        assert not result.healthy
        assert "not found" in result.reason
        assert result.days_until_expiry == 0.0

    def test_invalid_json(self, tmp_path):
        path = tmp_path / "token.json"
        path.write_text("not json{{{", encoding="utf-8")
        result = check_token_health(str(path))
        assert not result.healthy
        assert "unreadable" in result.reason

    def test_not_a_dict(self, tmp_path):
        path = tmp_path / "token.json"
        path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        result = check_token_health(str(path))
        assert not result.healthy
        assert "not a JSON object" in result.reason

    def test_missing_refresh_token(self, tmp_path):
        path = tmp_path / "token.json"
        path.write_text(json.dumps({"creation_timestamp": time.time()}), encoding="utf-8")
        result = check_token_health(str(path))
        assert not result.healthy
        assert "missing refresh_token" in result.reason

    def test_missing_creation_timestamp(self, tmp_path):
        path = tmp_path / "token.json"
        path.write_text(json.dumps({"refresh_token": "abc"}), encoding="utf-8")
        result = check_token_health(str(path))
        assert not result.healthy
        assert "missing creation_timestamp" in result.reason

    def test_invalid_creation_timestamp(self, tmp_path):
        path = tmp_path / "token.json"
        path.write_text(
            json.dumps({"refresh_token": "abc", "creation_timestamp": "not-a-number"}),
            encoding="utf-8",
        )
        result = check_token_health(str(path))
        assert not result.healthy
        assert "invalid creation_timestamp" in result.reason

    def test_expired_token(self, tmp_path):
        path = tmp_path / "token.json"
        old_ts = time.time() - (8 * 86400)  # 8 days ago
        path.write_text(
            json.dumps({"refresh_token": "abc", "creation_timestamp": old_ts}),
            encoding="utf-8",
        )
        result = check_token_health(str(path))
        assert not result.healthy
        assert "expired" in result.reason
        assert result.days_until_expiry == 0.0

    def test_healthy_fresh_token(self, tmp_path):
        path = tmp_path / "token.json"
        fresh_ts = time.time() - (1 * 86400)  # 1 day ago
        path.write_text(
            json.dumps({"refresh_token": "abc", "creation_timestamp": fresh_ts}),
            encoding="utf-8",
        )
        result = check_token_health(str(path))
        assert result.healthy
        assert result.reason is None
        assert 5.5 < result.days_until_expiry < 6.5  # ~6 days left

    def test_healthy_just_created(self, tmp_path):
        path = tmp_path / "token.json"
        path.write_text(
            json.dumps({"refresh_token": "abc", "creation_timestamp": time.time()}),
            encoding="utf-8",
        )
        result = check_token_health(str(path))
        assert result.healthy
        assert result.days_until_expiry > 6.9

    def test_token_about_to_expire(self, tmp_path):
        path = tmp_path / "token.json"
        almost_expired_ts = time.time() - (6.9 * 86400)  # 6.9 days ago
        path.write_text(
            json.dumps({"refresh_token": "abc", "creation_timestamp": almost_expired_ts}),
            encoding="utf-8",
        )
        result = check_token_health(str(path))
        assert result.healthy
        assert 0 < result.days_until_expiry < 0.2

    def test_token_exactly_at_limit(self, tmp_path):
        path = tmp_path / "token.json"
        expired_ts = time.time() - (7 * 86400)  # Exactly 7 days ago
        path.write_text(
            json.dumps({"refresh_token": "abc", "creation_timestamp": expired_ts}),
            encoding="utf-8",
        )
        result = check_token_health(str(path))
        assert not result.healthy
