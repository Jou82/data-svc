"""Alerta Discord (Incoming Webhook) — fail-open, sem PII.

Usado quando o data-svc esgota retries de DB (ex. lembretes/due).
Mesmo canal que o n8n (webhook no Easypanel), via env no data-svc:
`DISCORD_ALERT_WEBHOOK_URL`.

Nunca levanta: falha de rede/config só loga.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from src.config import Config

logger = logging.getLogger(__name__)

_TIMEOUT = 3.0


def _enabled() -> bool:
    return bool(Config.DISCORD_ALERT_WEBHOOK_URL)


def format_content(*, source: str, reason: str, detail: str = "") -> str:
    lines = [f"**MEIrelles {source}**", reason]
    if detail:
        lines.append(str(detail)[:1500])
    return "\n".join(lines).strip()[:1900]


def send_discord_alert(*, source: str, reason: str, detail: str = "") -> bool:
    """POST `{content}` ao webhook. True se 2xx; False se off/erro."""
    if not _enabled():
        return False
    content = format_content(source=source, reason=reason, detail=detail)
    try:
        body = json.dumps({"content": content}).encode("utf-8")
        req = urllib.request.Request(
            Config.DISCORD_ALERT_WEBHOOK_URL,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return 200 <= int(resp.status) < 300
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        logger.warning("discord_alert fail-open: %s", exc)
        return False
