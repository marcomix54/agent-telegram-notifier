#!/usr/bin/env python3
"""Send concise Telegram bot notifications for the agent-telegram-notifier skill."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any


MAX_TELEGRAM_TEXT = 4096
DEFAULT_CHUNK_SIZE = 3900
SETUP_SCRIPT = "setup_telegram.py"


class TelegramNotifyError(Exception):
    """Raised for user-facing notification failures."""


def redact(text: str, *secrets: str) -> str:
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    return redacted


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send a plain-text Telegram notification with sendMessage."
    )
    parser.add_argument(
        "message",
        nargs="*",
        help="Message text. If omitted, message text is read from stdin.",
    )
    parser.add_argument(
        "--no-split",
        action="store_true",
        help="Fail instead of splitting messages longer than Telegram's limit.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help="Number of retry attempts for transient failures. Default: 2.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Request timeout in seconds. Default: 10.",
    )
    parser.add_argument(
        "--disable-notification",
        action="store_true",
        help="Send silently without a push notification sound.",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate Telegram notifier environment variables without sending.",
    )
    return parser.parse_args()


def read_message(args: argparse.Namespace) -> str:
    if args.message:
        return " ".join(args.message).strip()
    if sys.stdin.isatty():
        raise TelegramNotifyError("No message provided. Pass text or pipe stdin.")
    return sys.stdin.read().strip()


def setup_script_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), SETUP_SCRIPT)


def get_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise TelegramNotifyError(
            f"Missing required environment variable: {name}. "
            f"Run {setup_script_path()} to configure Telegram Notifier."
        )
    return value


def load_config() -> tuple[str, str, str]:
    token = get_env("TELEGRAM_BOT_TOKEN")
    chat_id = get_env("TELEGRAM_CHAT_ID")
    api_base = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org").strip()
    if not api_base:
        api_base = "https://api.telegram.org"
    return token, chat_id, api_base


def split_text(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE) -> list[str]:
    if len(text) <= MAX_TELEGRAM_TEXT:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= chunk_size:
            chunks.append(remaining)
            break

        split_at = remaining.rfind("\n\n", 0, chunk_size)
        if split_at < chunk_size // 2:
            split_at = remaining.rfind("\n", 0, chunk_size)
        if split_at < chunk_size // 2:
            split_at = remaining.rfind(" ", 0, chunk_size)
        if split_at < chunk_size // 2:
            split_at = chunk_size

        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()

    total = len(chunks)
    if total == 1:
        return chunks

    prefixed = []
    for index, chunk in enumerate(chunks, start=1):
        prefix = f"({index}/{total})\n"
        if len(prefix) + len(chunk) > MAX_TELEGRAM_TEXT:
            chunk = chunk[: MAX_TELEGRAM_TEXT - len(prefix)]
        prefixed.append(prefix + chunk)
    return prefixed


def load_error_body(error: urllib.error.HTTPError) -> dict[str, Any]:
    try:
        raw = error.read().decode("utf-8", errors="replace")
        payload = json.loads(raw)
    except Exception:
        return {"ok": False, "description": f"HTTP {error.code}"}
    if isinstance(payload, dict):
        return payload
    return {"ok": False, "description": f"HTTP {error.code}"}


def retry_delay(payload: dict[str, Any], fallback: float) -> float:
    parameters = payload.get("parameters")
    if isinstance(parameters, dict):
        retry_after = parameters.get("retry_after")
        if isinstance(retry_after, (int, float)):
            return min(float(retry_after), 30.0)
    return fallback


def is_retryable_error(error_code: int | None) -> bool:
    if error_code is None:
        return True
    return error_code == 429 or 500 <= error_code <= 599


def post_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise TelegramNotifyError("Telegram returned an unexpected response.")
    return parsed


def send_message(
    *,
    token: str,
    chat_id: str,
    api_base: str,
    text: str,
    timeout: float,
    retries: int,
    disable_notification: bool,
) -> None:
    url = f"{api_base.rstrip('/')}/bot{token}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_notification": disable_notification,
    }

    attempts = max(0, retries) + 1
    delay = 1.0
    last_description = "Telegram notification failed."

    for attempt in range(1, attempts + 1):
        try:
            response = post_json(url, payload, timeout)
        except urllib.error.HTTPError as error:
            response = load_error_body(error)
            error_code = response.get("error_code")
            description = redact(
                str(response.get("description") or f"HTTP {error.code}"), token, chat_id
            )
            last_description = f"Telegram API error: {description}"
            if not is_retryable_error(error_code if isinstance(error_code, int) else None):
                break
            if attempt < attempts:
                time.sleep(retry_delay(response, delay))
                delay *= 2
                continue
            break
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last_description = (
                f"Network error while contacting Telegram: {type(error).__name__}. "
                "If this is running inside Codex with restricted network access, "
                "rerun with network permission or from an environment that can reach Telegram."
            )
            if attempt < attempts:
                time.sleep(delay)
                delay *= 2
                continue
            break
        except json.JSONDecodeError:
            last_description = "Telegram returned invalid JSON."
            if attempt < attempts:
                time.sleep(delay)
                delay *= 2
                continue
            break

        if response.get("ok") is True:
            return

        description = redact(
            str(response.get("description") or "Unknown Telegram API error."), token, chat_id
        )
        last_description = f"Telegram API error: {description}"
        error_code = response.get("error_code")
        if not is_retryable_error(error_code if isinstance(error_code, int) else None):
            break
        if attempt < attempts:
            time.sleep(retry_delay(response, delay))
            delay *= 2

    raise TelegramNotifyError(last_description)


def main() -> int:
    args = parse_args()
    try:
        token, chat_id, api_base = load_config()
        if args.check_config:
            print("agent-telegram-notifier: config ok")
            return 0

        message = read_message(args)
        if not message:
            raise TelegramNotifyError("Message is empty.")

        if len(message) > MAX_TELEGRAM_TEXT and args.no_split:
            raise TelegramNotifyError(
                f"Message is {len(message)} characters; Telegram limit is {MAX_TELEGRAM_TEXT}."
            )

        chunks = split_text(message)
        for chunk in chunks:
            send_message(
                token=token,
                chat_id=chat_id,
                api_base=api_base,
                text=chunk,
                timeout=args.timeout,
                retries=args.retries,
                disable_notification=args.disable_notification,
            )
    except TelegramNotifyError as error:
        print(f"agent-telegram-notifier: {error}", file=sys.stderr)
        return 1

    print("agent-telegram-notifier: sent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
