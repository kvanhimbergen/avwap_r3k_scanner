from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class SchwabReadonlyOAuthConfig:
    enabled: bool
    client_id: str
    client_secret: str
    redirect_uri: str
    token_path: str
    auth_url: str
    token_url: str
    account_hash: str


ENV_READONLY_ENABLED = "SCHWAB_READONLY_ENABLED"
ENV_CLIENT_ID = "SCHWAB_OAUTH_CLIENT_ID"
ENV_CLIENT_SECRET = "SCHWAB_OAUTH_CLIENT_SECRET"
ENV_REDIRECT_URI = "SCHWAB_OAUTH_REDIRECT_URI"
ENV_TOKEN_PATH = "SCHWAB_OAUTH_TOKEN_PATH"
ENV_AUTH_URL = "SCHWAB_OAUTH_AUTH_URL"
ENV_TOKEN_URL = "SCHWAB_OAUTH_TOKEN_URL"
ENV_ACCOUNT_HASH = "SCHWAB_ACCOUNT_HASH"

DEFAULT_AUTH_URL = "https://api.schwabapi.com/v1/oauth/authorize"
DEFAULT_TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"


def _get_env(env: Mapping[str, str] | None, key: str, default: str = "") -> str:
    if env is None:
        import os

        return os.getenv(key, default)
    return env.get(key, default)


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}


def load_schwab_readonly_oauth_config(
    env: Mapping[str, str] | None = None,
) -> SchwabReadonlyOAuthConfig:
    enabled = _truthy(_get_env(env, ENV_READONLY_ENABLED, "0"))
    return SchwabReadonlyOAuthConfig(
        enabled=enabled,
        client_id=_get_env(env, ENV_CLIENT_ID, "").strip(),
        client_secret=_get_env(env, ENV_CLIENT_SECRET, "").strip(),
        redirect_uri=_get_env(env, ENV_REDIRECT_URI, "").strip(),
        token_path=_get_env(env, ENV_TOKEN_PATH, "").strip(),
        auth_url=_get_env(env, ENV_AUTH_URL, DEFAULT_AUTH_URL).strip(),
        token_url=_get_env(env, ENV_TOKEN_URL, DEFAULT_TOKEN_URL).strip(),
        account_hash=_get_env(env, ENV_ACCOUNT_HASH, "").strip(),
    )
