from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


send_telegram = load_module("send_telegram", SCRIPTS / "send_telegram.py")
setup_telegram = load_module("setup_telegram", SCRIPTS / "setup_telegram.py")


class SetupTelegramTests(unittest.TestCase):
    def test_validate_token_returns_bot_details(self):
        with mock.patch.object(
            setup_telegram,
            "telegram_api",
            return_value={"ok": True, "result": {"username": "codex_test_bot"}},
        ) as api:
            result = setup_telegram.validate_token("123:abc", "https://api.telegram.org")

        self.assertEqual(result["username"], "codex_test_bot")
        api.assert_called_once_with(
            token="123:abc", method="getMe", api_base="https://api.telegram.org"
        )

    def test_extract_chats_deduplicates_and_labels(self):
        updates = [
            {
                "message": {
                    "chat": {
                        "id": 123,
                        "type": "private",
                        "first_name": "Ada",
                        "last_name": "Lovelace",
                    }
                }
            },
            {"edited_message": {"chat": {"id": "123", "type": "private", "first_name": "Ada"}}},
            {"channel_post": {"chat": {"id": -456, "type": "channel", "title": "Alerts"}}},
            {"message": {"text": "missing chat"}},
        ]

        chats = setup_telegram.extract_chats(updates)

        self.assertEqual(
            chats,
            [
                {"id": "123", "type": "private", "label": "Ada"},
                {"id": "-456", "type": "channel", "label": "Alerts"},
            ],
        )

    def test_redacts_token_from_setup_errors(self):
        with mock.patch.object(
            setup_telegram,
            "telegram_api",
            side_effect=setup_telegram.SetupError(
                "Telegram API error: bad token secret-token"
            ),
        ):
            with self.assertRaises(setup_telegram.SetupError) as raised:
                setup_telegram.validate_token("secret-token", "https://api.telegram.org")

        self.assertIn("secret-token", str(raised.exception))
        self.assertEqual(
            setup_telegram.redact(str(raised.exception), "secret-token"),
            "Telegram API error: bad token [redacted]",
        )

    def test_write_env_file_replaces_existing_managed_block(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agent-telegram-notifier.env"
            setup_telegram.write_env_file(path, "first-token", "111", "https://api.telegram.org")
            setup_telegram.write_env_file(path, "second-token", "222", "https://api.telegram.org")

            content = path.read_text(encoding="utf-8")

        self.assertEqual(content.count(setup_telegram.ENV_BLOCK_BEGIN), 1)
        self.assertNotIn("first-token", content)
        self.assertNotIn("111", content)
        self.assertIn("second-token", content)
        self.assertIn("222", content)

    def test_write_env_file_preserves_unmanaged_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shell.env"
            path.write_text("export KEEP_ME=1\n", encoding="utf-8")
            setup_telegram.write_env_file(path, "secret-token", "456", "https://api.telegram.org")

            content = path.read_text(encoding="utf-8")

        self.assertIn("export KEEP_ME=1", content)
        self.assertIn(setup_telegram.ENV_BLOCK_BEGIN, content)

    def test_file_output_redaction_helper_masks_secrets(self):
        rendered = "\n".join(
            setup_telegram.shell_export_lines(
                "secret-token", "secret-chat", "https://api.telegram.org"
            )
        )

        redacted = setup_telegram.redact(rendered, "secret-token", "secret-chat")

        self.assertNotIn("secret-token", redacted)
        self.assertNotIn("secret-chat", redacted)
        self.assertEqual(redacted.count("[redacted]"), 2)


class SendTelegramTests(unittest.TestCase):
    def test_check_config_passes_without_message(self):
        env = {
            "TELEGRAM_BOT_TOKEN": "123:abc",
            "TELEGRAM_CHAT_ID": "456",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(sys, "argv", ["send_telegram.py", "--check-config"]):
                with mock.patch("builtins.print") as printed:
                    result = send_telegram.main()

        self.assertEqual(result, 0)
        printed.assert_called_once_with("agent-telegram-notifier: config ok")

    def test_missing_config_points_to_setup_script(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(send_telegram.TelegramNotifyError) as raised:
                send_telegram.load_config()

        message = str(raised.exception)
        self.assertIn("Missing required environment variable: TELEGRAM_BOT_TOKEN", message)
        self.assertIn("setup_telegram.py", message)

    def test_redacts_token_and_chat_id_from_api_errors(self):
        with mock.patch.object(
            send_telegram,
            "post_json",
            return_value={
                "ok": False,
                "description": "token 123:abc chat 456 failed",
                "error_code": 400,
            },
        ):
            with self.assertRaises(send_telegram.TelegramNotifyError) as raised:
                send_telegram.send_message(
                    token="123:abc",
                    chat_id="456",
                    api_base="https://api.telegram.org",
                    text="hello",
                    timeout=1,
                    retries=0,
                    disable_notification=False,
                )

        message = str(raised.exception)
        self.assertNotIn("123:abc", message)
        self.assertNotIn("456", message)
        self.assertIn("[redacted]", message)

    def test_long_messages_split_with_prefixes(self):
        chunks = send_telegram.split_text("x" * 5000, chunk_size=3900)

        self.assertEqual(len(chunks), 2)
        self.assertTrue(chunks[0].startswith("(1/2)\n"))
        self.assertTrue(chunks[1].startswith("(2/2)\n"))
        self.assertTrue(all(len(chunk) <= send_telegram.MAX_TELEGRAM_TEXT for chunk in chunks))

    def test_retryable_failure_retries(self):
        calls = []

        def fake_post_json(url, payload, timeout):
            calls.append((url, payload, timeout))
            if len(calls) == 1:
                return {"ok": False, "description": "try again", "error_code": 500}
            return {"ok": True}

        with mock.patch.object(send_telegram, "post_json", side_effect=fake_post_json):
            with mock.patch.object(send_telegram.time, "sleep"):
                send_telegram.send_message(
                    token="123:abc",
                    chat_id="456",
                    api_base="https://api.telegram.org",
                    text="hello",
                    timeout=1,
                    retries=1,
                    disable_notification=False,
                )

        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
