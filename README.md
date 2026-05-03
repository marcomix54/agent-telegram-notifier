# Agent Telegram Notifier

[![Test](https://github.com/marcomix54/agent-telegram-notifier/actions/workflows/test.yml/badge.svg)](https://github.com/marcomix54/agent-telegram-notifier/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Agent Telegram Notifier is a Codex skill for sending one concise plain-text Telegram notification after an agent task, automation, monitoring run, or long-running job finishes.

It is intentionally small: it sends final status summaries through a user-provided Telegram bot. It is not a Telegram chatbot framework, incoming message handler, attachment sender, rich formatting layer, or multi-recipient router.

## Requirements

- Python 3.9 or newer.
- No third-party Python dependencies.
- A Telegram bot token from `@BotFather`.
- A target Telegram account, group, or channel that has started or added the bot.

Keep bot tokens and chat IDs out of source control, prompts, logs, and generated reports. If a token is pasted into a chat or log by mistake, rotate it with `@BotFather`.

## Install

Install from GitHub with the Codex skill installer:

```bash
python3 ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo marcomix54/agent-telegram-notifier \
  --path . \
  --name agent-telegram-notifier
```

Then restart Codex so the new skill is picked up.

Manual install is also possible:

```bash
mkdir -p ~/.codex/skills/agent-telegram-notifier
cp -R SKILL.md agents scripts ~/.codex/skills/agent-telegram-notifier/
```

## Setup

Create a Telegram bot with `@BotFather`, then run the setup wizard from the installed skill:

```bash
python3 ~/.codex/skills/agent-telegram-notifier/scripts/setup_telegram.py
```

If you are working from a local checkout of this repository, you can run the same wizard from the checkout:

```bash
python3 scripts/setup_telegram.py
```

The wizard:

- Prompts for the bot token without echoing it.
- Validates the token with Telegram `getMe`.
- Asks you to send `/start` to the bot.
- Detects the target chat with `getUpdates`.
- Sends a test notification.
- Offers three storage choices: print exports only, append to a shell env file, or write a private Codex env file.

The sender reads configuration from environment variables:

```bash
export TELEGRAM_BOT_TOKEN='token-from-botfather'
export TELEGRAM_CHAT_ID='chat-id-from-getUpdates'
```

Optional:

```bash
export TELEGRAM_API_BASE='https://api.telegram.org'
```

Check configuration without sending:

```bash
python3 ~/.codex/skills/agent-telegram-notifier/scripts/send_telegram.py --check-config
```

Send a test message:

```bash
python3 ~/.codex/skills/agent-telegram-notifier/scripts/send_telegram.py "Telegram notifier test from Codex."
```

From a local checkout, use `python3 scripts/send_telegram.py ...` instead.

## Usage

Ask Codex to use the skill at the end of a task:

```text
After the task is complete, use $agent-telegram-notifier to send me one concise Telegram summary with title, status, key findings, and next step. Send the notification even if the task partially fails.
```

For multi-line messages:

```bash
printf '%s\n' "Weekly report" "Status: success" "" "- Finished the run." "" "Next step: No action needed." \
  | python3 scripts/send_telegram.py
```

Messages longer than Telegram's 4096-character limit are split safely by default. Use `--no-split` to fail instead.

## Troubleshooting

`Missing required environment variable`: run `scripts/setup_telegram.py` or export `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in the environment that runs Codex or the automation.

`Network error while contacting Telegram`: Telegram delivery requires outbound access to `api.telegram.org` or your configured `TELEGRAM_API_BASE`. In restricted Codex sandboxes, rerun the sender with a narrow network permission approval.

No chat detected during setup: send `/start` directly to the bot from the target account or add the bot to the target group/channel, then rerun setup.

## Development

Run tests:

```bash
python3 -m unittest discover -s tests
```

Run syntax checks:

```bash
python3 -m py_compile scripts/send_telegram.py scripts/setup_telegram.py
```

This project uses only the Python standard library. Keep the installed skill bundle lean: `SKILL.md`, `agents/`, and `scripts/` are the runtime pieces; tests and GitHub metadata are for the repository.

## License

MIT
