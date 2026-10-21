"""WhatsApp Business API client for sending messages."""

import logging
import time

import requests

import config

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_BASE = 2  # seconds


def _send_request(payload: dict) -> dict:
    """Send a message via WhatsApp Business API with retry logic."""
    headers = {
        "Authorization": f"Bearer {config.WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(
                config.WHATSAPP_API_URL,
                json=payload,
                headers=headers,
                timeout=30,
            )

            if response.status_code == 429:
                wait = BACKOFF_BASE ** (attempt + 1)
                logger.warning("Rate limited by WhatsApp API, waiting %ds", wait)
                time.sleep(wait)
                continue

            response.raise_for_status()
            return response.json()

        except requests.exceptions.ConnectionError:
            if attempt < MAX_RETRIES - 1:
                wait = BACKOFF_BASE ** attempt
                logger.warning("Connection error, retrying in %ds", wait)
                time.sleep(wait)
                continue
            raise
        except requests.exceptions.HTTPError:
            if attempt < MAX_RETRIES - 1 and response.status_code >= 500:
                wait = BACKOFF_BASE ** (attempt + 1)
                logger.warning("Server error %d, retrying in %ds", response.status_code, wait)
                time.sleep(wait)
                continue
            logger.error(
                "WhatsApp API error %d: %s", response.status_code, response.text
            )
            raise

    raise RuntimeError("Max retries exceeded for WhatsApp API")


def _describe_payload(payload: dict) -> str:
    """Human-readable text of a sent message, for the Chatwoot note."""
    msg_type = payload.get("type")
    if msg_type == "text":
        return payload.get("text", {}).get("body", "")
    if msg_type == "interactive":
        return payload.get("interactive", {}).get("body", {}).get("text", "")
    if msg_type == "template":
        template = payload.get("template", {})
        params = [
            p.get("text", "")
            for c in template.get("components", [])
            if c.get("type") == "body"
            for p in c.get("parameters", [])
            if p.get("type") == "text"
        ]
        return f"תבנית {template.get('name', '')}: " + " | ".join(params)
    return f"הודעה מסוג {msg_type}"


def _log_to_chatwoot(payload: dict) -> None:
    """Best effort: a failed note must never fail the reminder itself."""
    if not config.CHATWOOT_NOTE_URL or not config.CHATWOOT_NOTE_KEY:
        return
    recipient = str(payload.get("to", ""))
    if not recipient or recipient == config.MY_WHATSAPP_NUMBER:
        return
    try:
        requests.post(
            config.CHATWOOT_NOTE_URL,
            json={"phone": recipient, "text": _describe_payload(payload)},
            headers={"x-api-key": config.CHATWOOT_NOTE_KEY},
            timeout=10,
        )
    except requests.exceptions.RequestException as exc:
        logger.warning("Chatwoot note failed for %s: %s", recipient, exc)


def send_interactive_message(payload: dict) -> str:
    """Send an interactive button message. Returns the WhatsApp message ID."""
    result = _send_request(payload)
    messages = result.get("messages", [])
    if messages:
        msg_id = messages[0].get("id", "")
        logger.info("Interactive message sent, id=%s", msg_id)
        _log_to_chatwoot(payload)
        return msg_id
    logger.warning("No message ID in response: %s", result)
    return ""


def send_text_message(payload: dict) -> str:
    """Send a plain text message. Returns the WhatsApp message ID."""
    result = _send_request(payload)
    messages = result.get("messages", [])
    if messages:
        msg_id = messages[0].get("id", "")
        logger.info("Text message sent, id=%s", msg_id)
        _log_to_chatwoot(payload)
        return msg_id
    logger.warning("No message ID in response: %s", result)
    return ""
