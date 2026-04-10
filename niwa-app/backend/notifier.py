"""Niwa notifier — lightweight webhook/Telegram notifications.

Zero external deps. Uses urllib only. Falls back silently on failure.

Reads credentials from:
  1. New service keys (svc.notify.telegram.*, svc.notify.webhook.*) — priority
  2. Legacy integration keys (int.telegram_*, int.webhook_url) — fallback
  3. Environment variables (NIWA_TELEGRAM_BOT_TOKEN, etc.) — last resort

Usage:
    from notifier import send_notification
    send_notification("Task completed: fix login bug", channel="telegram")
    send_notification("Backup done", channel="webhook", url="https://example.com/hook")
"""

import json
import logging
import os
import urllib.error
import urllib.request

log = logging.getLogger("niwa-notifier")

# Env-var defaults (last resort)
TELEGRAM_BOT_TOKEN = os.environ.get("NIWA_TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("NIWA_TELEGRAM_CHAT_ID", "").strip()
GENERIC_WEBHOOK_URL = os.environ.get("NIWA_WEBHOOK_URL", "").strip()


def _get_db_setting(key):
    """Try to read a setting from the DB without importing app at module load time."""
    try:
        from app import fetch_setting_raw
        return fetch_setting_raw(key) or ""
    except Exception:
        return ""


def _resolve_telegram_creds(bot_token="", chat_id=""):
    """Resolve Telegram credentials: explicit args > svc keys > int keys > env vars."""
    token = bot_token or _get_db_setting("svc.notify.telegram.bot_token") or _get_db_setting("int.telegram_bot_token") or TELEGRAM_BOT_TOKEN
    cid = chat_id or _get_db_setting("svc.notify.telegram.chat_id") or _get_db_setting("int.telegram_chat_id") or TELEGRAM_CHAT_ID
    return token, cid


def _resolve_webhook_url(url=""):
    """Resolve webhook URL: explicit arg > svc keys > int keys > env vars."""
    return url or _get_db_setting("svc.notify.webhook.url") or _get_db_setting("int.webhook_url") or GENERIC_WEBHOOK_URL


def send_telegram(text: str, chat_id: str = "", bot_token: str = "") -> bool:
    token, cid = _resolve_telegram_creds(bot_token, chat_id)
    if not token or not cid:
        log.debug("Telegram not configured (missing token or chat_id)")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": cid, "text": text, "parse_mode": "Markdown"}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        log.warning("Telegram send failed: %s", e)
        return False


def send_webhook(text: str, url: str = "") -> bool:
    target = _resolve_webhook_url(url)
    if not target:
        log.debug("Webhook not configured")
        return False
    payload = json.dumps({"text": text, "source": "niwa"}).encode()
    req = urllib.request.Request(target, data=payload, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        log.warning("Webhook send failed to %s: %s", target, e)
        return False


def send_notification(text: str, channel: str = "telegram", **kwargs) -> bool:
    """Send a notification via the specified channel.

    Args:
        text: message body
        channel: 'telegram', 'webhook', or 'none'
        **kwargs: forwarded to the channel function (e.g. url, chat_id, bot_token)
    """
    if channel == "none":
        return True
    if channel == "telegram":
        return send_telegram(text, **kwargs)
    if channel == "webhook":
        return send_webhook(text, **kwargs)
    log.warning("Unknown notification channel: %s", channel)
    return False
