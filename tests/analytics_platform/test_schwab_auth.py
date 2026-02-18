from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from analytics.schwab_auth import run_auth_flow


class TestRunAuthFlow:
    def test_missing_client_id(self, monkeypatch):
        monkeypatch.setenv("SCHWAB_OAUTH_CLIENT_ID", "")
        monkeypatch.setenv("SCHWAB_OAUTH_CLIENT_SECRET", "")
        monkeypatch.setenv("SCHWAB_OAUTH_REDIRECT_URI", "https://example.com/cb")
        monkeypatch.setenv("SCHWAB_OAUTH_TOKEN_PATH", "/tmp/token.json")
        monkeypatch.setenv("SCHWAB_READONLY_ENABLED", "0")
        monkeypatch.setenv("SCHWAB_ACCOUNT_HASH", "")
        result = run_auth_flow()
        assert result == 1

    def test_missing_redirect_uri(self, monkeypatch):
        monkeypatch.setenv("SCHWAB_OAUTH_CLIENT_ID", "test-id")
        monkeypatch.setenv("SCHWAB_OAUTH_CLIENT_SECRET", "test-secret")
        monkeypatch.setenv("SCHWAB_OAUTH_REDIRECT_URI", "")
        monkeypatch.setenv("SCHWAB_OAUTH_TOKEN_PATH", "/tmp/token.json")
        monkeypatch.setenv("SCHWAB_READONLY_ENABLED", "0")
        monkeypatch.setenv("SCHWAB_ACCOUNT_HASH", "")
        result = run_auth_flow()
        assert result == 1

    def test_missing_token_path(self, monkeypatch):
        monkeypatch.setenv("SCHWAB_OAUTH_CLIENT_ID", "test-id")
        monkeypatch.setenv("SCHWAB_OAUTH_CLIENT_SECRET", "test-secret")
        monkeypatch.setenv("SCHWAB_OAUTH_REDIRECT_URI", "https://example.com/cb")
        monkeypatch.setenv("SCHWAB_OAUTH_TOKEN_PATH", "")
        monkeypatch.setenv("SCHWAB_READONLY_ENABLED", "0")
        monkeypatch.setenv("SCHWAB_ACCOUNT_HASH", "")
        result = run_auth_flow()
        assert result == 1

    def test_successful_flow(self, monkeypatch):
        monkeypatch.setenv("SCHWAB_OAUTH_CLIENT_ID", "test-id")
        monkeypatch.setenv("SCHWAB_OAUTH_CLIENT_SECRET", "test-secret")
        monkeypatch.setenv("SCHWAB_OAUTH_REDIRECT_URI", "https://example.com/cb")
        monkeypatch.setenv("SCHWAB_OAUTH_TOKEN_PATH", "/tmp/token.json")
        monkeypatch.setenv("SCHWAB_READONLY_ENABLED", "0")
        monkeypatch.setenv("SCHWAB_ACCOUNT_HASH", "")

        mock_client = MagicMock()
        mock_schwab = MagicMock()
        mock_schwab.auth.client_from_manual_flow.return_value = mock_client

        account_resp = MagicMock()
        account_resp.status_code = 200
        account_resp.json.return_value = [
            {"accountNumber": "12345", "hashValue": "abc123hash"},
        ]
        mock_client.get_account_numbers.return_value = account_resp

        monkeypatch.setitem(sys.modules, "schwab", mock_schwab)
        result = run_auth_flow()
        assert result == 0
        mock_schwab.auth.client_from_manual_flow.assert_called_once()

    def test_flow_account_numbers_failure(self, monkeypatch):
        monkeypatch.setenv("SCHWAB_OAUTH_CLIENT_ID", "test-id")
        monkeypatch.setenv("SCHWAB_OAUTH_CLIENT_SECRET", "test-secret")
        monkeypatch.setenv("SCHWAB_OAUTH_REDIRECT_URI", "https://example.com/cb")
        monkeypatch.setenv("SCHWAB_OAUTH_TOKEN_PATH", "/tmp/token.json")
        monkeypatch.setenv("SCHWAB_READONLY_ENABLED", "0")
        monkeypatch.setenv("SCHWAB_ACCOUNT_HASH", "")

        mock_client = MagicMock()
        mock_schwab = MagicMock()
        mock_schwab.auth.client_from_manual_flow.return_value = mock_client

        account_resp = MagicMock()
        account_resp.status_code = 500
        mock_client.get_account_numbers.return_value = account_resp

        monkeypatch.setitem(sys.modules, "schwab", mock_schwab)
        result = run_auth_flow()
        assert result == 0  # Still succeeds — token was saved

    def test_flow_no_accounts(self, monkeypatch):
        monkeypatch.setenv("SCHWAB_OAUTH_CLIENT_ID", "test-id")
        monkeypatch.setenv("SCHWAB_OAUTH_CLIENT_SECRET", "test-secret")
        monkeypatch.setenv("SCHWAB_OAUTH_REDIRECT_URI", "https://example.com/cb")
        monkeypatch.setenv("SCHWAB_OAUTH_TOKEN_PATH", "/tmp/token.json")
        monkeypatch.setenv("SCHWAB_READONLY_ENABLED", "0")
        monkeypatch.setenv("SCHWAB_ACCOUNT_HASH", "")

        mock_client = MagicMock()
        mock_schwab = MagicMock()
        mock_schwab.auth.client_from_manual_flow.return_value = mock_client

        account_resp = MagicMock()
        account_resp.status_code = 200
        account_resp.json.return_value = []
        mock_client.get_account_numbers.return_value = account_resp

        monkeypatch.setitem(sys.modules, "schwab", mock_schwab)
        result = run_auth_flow()
        assert result == 0
