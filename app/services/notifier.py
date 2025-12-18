from __future__ import annotations

import requests

from app.config import settings


def notify_mattermost(text: str) -> bool:
    url = (settings.mattermost_webhook_url or "").strip()
    if not url:
        return False
    resp = requests.post(url, json={"text": text}, timeout=20)
    resp.raise_for_status()
    return True

