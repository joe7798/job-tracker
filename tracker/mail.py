"""Microsoft Graph API mail fetcher using MSAL device-code flow."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import msal
import requests

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_SCOPES = ["Mail.Read"]
_TOKEN_CACHE_PATH = Path("token_cache.bin")

# Personal-account authority — required for Outlook.com / Hotmail device-code flow.
_AUTHORITY = "https://login.microsoftonline.com/consumers"


def _load_cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if _TOKEN_CACHE_PATH.exists():
        cache.deserialize(_TOKEN_CACHE_PATH.read_text(encoding="utf-8"))
    return cache


def _save_cache(cache: msal.SerializableTokenCache) -> None:
    if cache.has_state_changed:
        _TOKEN_CACHE_PATH.write_text(cache.serialize(), encoding="utf-8")


def _build_app(client_id: str) -> tuple[msal.PublicClientApplication, msal.SerializableTokenCache]:
    cache = _load_cache()
    app = msal.PublicClientApplication(
        client_id,
        authority=_AUTHORITY,
        token_cache=cache,
    )
    return app, cache


def get_access_token(client_id: str) -> str:
    """Return a valid access token, prompting device-code login if needed."""
    app, cache = _build_app(client_id)

    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(_SCOPES, account=accounts[0])
        if result and "access_token" in result:
            _save_cache(cache)
            return result["access_token"]

    flow = app.initiate_device_flow(scopes=_SCOPES)
    if "user_code" not in flow:
        raise RuntimeError(
            f"Failed to start device-code flow. Check your AZURE_CLIENT_ID and that "
            f"'Allow public client flows' is enabled in the Azure portal.\n"
            f"Error: {flow.get('error_description', flow)}"
        )

    print("\n" + flow["message"])
    print("(See README.md § Azure App Registration if you need setup help)\n")

    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise RuntimeError(
            f"Authentication failed: {result.get('error_description', result)}\n"
            "See README.md § Azure App Registration for troubleshooting."
        )

    _save_cache(cache)
    return result["access_token"]


def fetch_recent_messages(client_id: str, lookback_days: int) -> list[dict[str, Any]]:
    """Fetch inbox messages received within the lookback window."""
    token = get_access_token(client_id)
    headers = {"Authorization": f"Bearer {token}"}

    since = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    params = {
        "$filter": f"receivedDateTime ge {since}",
        "$select": "id,subject,from,bodyPreview,receivedDateTime",
        "$orderby": "receivedDateTime desc",
        "$top": "250",
    }

    resp = requests.get(f"{_GRAPH_BASE}/me/messages", headers=headers, params=params, timeout=30)

    if resp.status_code == 401:
        raise RuntimeError(
            "Graph API returned 401 Unauthorized. Delete token_cache.bin and re-run "
            "to force a fresh login. See README.md § Azure App Registration."
        )
    resp.raise_for_status()

    messages = resp.json().get("value", [])
    return [
        {
            "id": m["id"],
            "subject": m.get("subject", ""),
            "sender_name": m.get("from", {}).get("emailAddress", {}).get("name", ""),
            "sender_address": m.get("from", {}).get("emailAddress", {}).get("address", ""),
            "body_preview": m.get("bodyPreview", ""),
            "received": m.get("receivedDateTime", ""),
        }
        for m in messages
    ]
