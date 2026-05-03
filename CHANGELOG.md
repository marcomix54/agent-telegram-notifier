# Changelog

All notable changes to Agent Telegram Notifier will be documented in this file.

## 0.1.0 - 2026-05-03

- Initial public release of the Codex Telegram notification skill.
- Added the `SKILL.md` runtime instructions for final task and automation notifications.
- Added the `send_telegram.py` sender with environment validation, retries, secret redaction, and long-message splitting.
- Added the `setup_telegram.py` guided setup wizard for BotFather tokens, chat detection, test delivery, and optional local env storage.
- Added Codex agent metadata in `agents/openai.yaml`.
- Added unit tests and GitHub Actions CI.
