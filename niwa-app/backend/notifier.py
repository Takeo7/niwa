"""Niwa notifier — lightweight webhook/Telegram notifications.

Zero external deps. Uses urllib only. Falls back silently on failure.

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

TELEGRAM_BOT_TOKEN = os.environ.get("NIWA_TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("NIWA_TELEGRAM_CHAT_ID", "").strip()
GENERIC_WEBHOOK_URL = os.environ.get("NIWA_WEBHOOK_URL", "").strip()


def send_telegram(text: str, chat_id: str = "", bot_token: str = "") -> bool:
    token = bot_token or TELEGRAM_BOT_TOKEN
    cid = chat_id or TELEGRAM_CHAT_ID
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
    target = url or GENERIC_WEBHOOK_URL
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
