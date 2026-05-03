#!/usr/bin/env python3
"""Interactive setup wizard for the agent-telegram-notifier skill."""

from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import shlex
import stat
import sys
import time
import urllib.error
import urllib.request
from typing import Any


DEFAULT_API_BASE = "https://api.telegram.org"
DEFAULT_TEST_MESSAGE = "Telegram notifier test from Codex."
ENV_BOT_TOKEN = "TELEGRAM_BOT_TOKEN"
ENV_CHAT_ID = "TELEGRAM_CHAT_ID"
ENV_API_BASE = "TELEGRAM_API_BASE"
ENV_BLOCK_BEGIN = "# >>> Agent Telegram Notifier for Codex >>>"
ENV_BLOCK_END = "# <<< Agent Telegram Notifier for Codex <<<"


class SetupError(Exception):
    """Raised for setup failures that are safe to show to the user."""


def redact(text: str, *secrets: str) -> str:
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    return redacted


def telegram_api(
    *,
    token: str,
    method: str,
    api_base: str = DEFAULT_API_BASE,
    payload: dict[str, Any] | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    url = f"{api_base.rstrip('/')}/bot{token}/{method}"
    data = json.dumps(payload or {}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        description = f"HTTP {error.code}"
        try:
            body = json.loads(error.read().decode("utf-8", errors="replace"))
            if isinstance(body, dict) and body.get("description"):
                description = str(body["description"])
        except Exception:
            pass
        raise SetupError(f"Telegram API error: {redact(description, token)}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise SetupError(
            "Network error while contacting Telegram. "
            "If you are running inside Codex with restricted network access, "
            "rerun with network permission or run this setup from a normal shell."
        ) from error

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        raise SetupError("Telegram returned invalid JSON.") from error

    if not isinstance(parsed, dict):
        raise SetupError("Telegram returned an unexpected response.")
    if parsed.get("ok") is not True:
        description = redact(
            str(parsed.get("description") or "Unknown Telegram API error."), token
        )
        raise SetupError(f"Telegram API error: {description}")
    return parsed


def validate_token(token: str, api_base: str) -> dict[str, Any]:
    if not token.strip():
        raise SetupError("Bot token is required.")
    response = telegram_api(token=token.strip(), method="getMe", api_base=api_base)
    result = response.get("result")
    if not isinstance(result, dict):
        raise SetupError("Telegram did not return bot details.")
    return result


def extract_chats(updates: list[dict[str, Any]]) -> list[dict[str, str]]:
    chats: dict[str, dict[str, str]] = {}
    holders = (
        "message",
        "edited_message",
        "channel_post",
        "edited_channel_post",
        "my_chat_member",
        "chat_member",
    )
    for update in updates:
        for key in holders:
            item = update.get(key)
            if not isinstance(item, dict):
                continue
            chat = item.get("chat")
            if not isinstance(chat, dict) or chat.get("id") is None:
                continue
            chat_id = str(chat["id"])
            label = (
                str(chat.get("title") or chat.get("username") or "").strip()
                or " ".join(
                    str(part)
                    for part in (chat.get("first_name"), chat.get("last_name"))
                    if part
                ).strip()
            )
            chats[chat_id] = {
                "id": chat_id,
                "type": str(chat.get("type") or ""),
                "label": label,
            }
    return list(chats.values())


def get_updates(token: str, api_base: str, timeout: float) -> list[dict[str, Any]]:
    response = telegram_api(
        token=token,
        method="getUpdates",
        api_base=api_base,
        payload={"allowed_updates": ["message", "channel_post", "my_chat_member"]},
        timeout=timeout,
    )
    result = response.get("result")
    if not isinstance(result, list):
        raise SetupError("Telegram did not return an updates list.")
    return [item for item in result if isinstance(item, dict)]


def poll_chats(
    *,
    token: str,
    api_base: str,
    attempts: int = 12,
    interval: float = 5.0,
    timeout: float = 10.0,
) -> list[dict[str, str]]:
    for attempt in range(1, attempts + 1):
        chats = extract_chats(get_updates(token, api_base, timeout))
        if chats:
            return chats
        if attempt < attempts:
            print("No chat found yet. Waiting for /start...")
            time.sleep(interval)
    return []


def choose_chat(chats: list[dict[str, str]]) -> dict[str, str]:
    if len(chats) == 1:
        chat = chats[0]
        print(f"Using chat {chat['id']} ({chat.get('label') or chat.get('type') or 'unknown'}).")
        return chat

    print("Detected chats:")
    for index, chat in enumerate(chats, start=1):
        label = chat.get("label") or chat.get("type") or "unknown"
        print(f"  {index}. {chat['id']} - {label}")

    while True:
        raw = input("Choose a chat number: ").strip()
        try:
            choice = int(raw)
        except ValueError:
            print("Enter a number from the list.")
            continue
        if 1 <= choice <= len(chats):
            return chats[choice - 1]
        print("Enter a number from the list.")


def shell_export_lines(token: str, chat_id: str, api_base: str) -> list[str]:
    lines = [
        f"export {ENV_BOT_TOKEN}={shlex.quote(token)}",
        f"export {ENV_CHAT_ID}={shlex.quote(chat_id)}",
    ]
    if api_base.rstrip("/") != DEFAULT_API_BASE:
        lines.append(f"export {ENV_API_BASE}={shlex.quote(api_base)}")
    return lines


def write_env_file(path: Path, token: str, chat_id: str, api_base: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    block = "\n".join([ENV_BLOCK_BEGIN, *shell_export_lines(token, chat_id, api_base), ENV_BLOCK_END])
    begin = existing.find(ENV_BLOCK_BEGIN)
    end = existing.find(ENV_BLOCK_END)
    if begin != -1 and end != -1 and begin < end:
        end += len(ENV_BLOCK_END)
        updated = existing[:begin].rstrip() + "\n\n" + block + "\n" + existing[end:].lstrip()
    else:
        updated = existing.rstrip() + "\n\n" + block + "\n"
    path.write_text(updated.lstrip(), encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def send_test(token: str, chat_id: str, api_base: str) -> None:
    script_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(script_dir))
    import send_telegram  # type: ignore

    send_telegram.send_message(
        token=token,
        chat_id=chat_id,
        api_base=api_base,
        text=DEFAULT_TEST_MESSAGE,
        timeout=10.0,
        retries=2,
        disable_notification=False,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Configure Telegram Notifier with a guided interactive wizard."
    )
    parser.add_argument(
        "--api-base",
        default=None,
        help=f"Telegram API base. Default: {DEFAULT_API_BASE}",
    )
    return parser.parse_args()


def print_guided_exports(token: str, chat_id: str, api_base: str) -> None:
    print("\nAdd these exports to the environment used by Codex and automations:")
    print()
    for line in shell_export_lines(token, chat_id, api_base):
        print(line)
    print()
    sender = Path(__file__).resolve().with_name("send_telegram.py")
    print("Then test with:")
    print(f"python3 {shlex.quote(str(sender))} {shlex.quote(DEFAULT_TEST_MESSAGE)}")


def store_config(token: str, chat_id: str, api_base: str) -> None:
    print("\nHow should setup store these values?")
    print("  1. Guided only (default): print export commands; do not write secrets.")
    print("  2. Write shell env: append exports to a shell startup file.")
    print("  3. Codex env file: write ~/.codex/agent-telegram-notifier.env.")
    choice = input("Choose 1, 2, or 3 [1]: ").strip() or "1"

    if choice == "2":
        default_path = Path.home() / ".zshenv"
        raw_path = input(f"Shell env file [{default_path}]: ").strip()
        path = Path(raw_path).expanduser() if raw_path else default_path
        confirm = input(f"Append Telegram exports to {path}? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Skipped writing shell env file.")
            print_guided_exports(token, chat_id, api_base)
            return
        write_env_file(path, token, chat_id, api_base)
        print(f"Wrote Telegram notifier exports to {path}.")
        return

    if choice == "3":
        path = Path.home() / ".codex" / "agent-telegram-notifier.env"
        confirm = input(f"Write private env file at {path}? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Skipped writing Codex env file.")
            print_guided_exports(token, chat_id, api_base)
            return
        write_env_file(path, token, chat_id, api_base)
        print(f"Wrote private env file to {path}.")
        print(f"Source it with: . {shlex.quote(str(path))}")
        return

    print_guided_exports(token, chat_id, api_base)


def main() -> int:
    args = parse_args()
    print("Telegram Notifier setup")
    print("Create a bot with @BotFather first, then paste the token below.")
    api_base = (
        args.api_base
        or input(f"Telegram API base [{DEFAULT_API_BASE}]: ").strip()
        or DEFAULT_API_BASE
    )
    token = getpass.getpass("Bot token (hidden): ").strip()

    try:
        bot = validate_token(token, api_base)
        username = bot.get("username")
        print(f"Validated bot{f' @{username}' if username else ''}.")
        input("Send /start to this bot from the target chat, then press Enter.")
        chats = poll_chats(token=token, api_base=api_base)
        if not chats:
            raise SetupError("No chat found. Send /start to the bot and run setup again.")
        chat = choose_chat(chats)
        send_test(token, chat["id"], api_base)
        print("Test notification sent.")
        store_config(token, chat["id"], api_base)
    except SetupError as error:
        print(f"agent-telegram-notifier setup: {error}", file=sys.stderr)
        return 1

    print("\nSetup complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
