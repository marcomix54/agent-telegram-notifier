---
name: agent-telegram-notifier
description: Send concise Telegram bot notifications from Codex or agent threads, recurring automations, monitoring tasks, reports, and long-running jobs when the user wants a final success, partial, or failure summary delivered through a Telegram bot.
---

# Agent Telegram Notifier

Use this skill to send one concise plain-text Telegram notification through a user-provided bot. It is designed for final automation updates, not live chatbots, incoming Telegram handling, attachments, rich formatting, or multi-recipient routing.

## Requirements

Use environment variables for all configuration:

- `TELEGRAM_BOT_TOKEN`: required bot token from BotFather.
- `TELEGRAM_CHAT_ID`: required default chat ID to notify.
- `TELEGRAM_API_BASE`: optional API base, defaults to `https://api.telegram.org`.

Never store bot tokens or chat IDs inside the skill files, prompts, generated reports, or source-controlled artifacts. Do not print token values when reporting errors.

## Not Configured Yet

If this skill is invoked but `TELEGRAM_BOT_TOKEN` or `TELEGRAM_CHAT_ID` is missing, do not treat that as a normal task failure. Tell the user that Telegram notifications are installed but not set up yet, then offer to walk them through the setup workflow.

Use wording like:

```text
Agent Telegram Notifier is installed, but it is not configured yet. I need a Telegram bot token and target chat ID in the environment before I can send notifications. I can help you set that up with BotFather and a test message.
```

For recurring automations, report the underlying automation result locally and clearly note that the Telegram notification was skipped because setup is incomplete.

## Setup Workflow

When helping a user set this up:

1. Ask them to create a bot with `@BotFather` in Telegram and copy the token.
2. Run the setup wizard from this skill directory:

```bash
python3 scripts/setup_telegram.py
```

3. The wizard validates the bot token with `getMe`, asks the user to send `/start`, detects the target chat from `getUpdates`, sends a test message, and offers setup storage options.
4. Default storage is guided-only: the wizard prints exact `export` commands without writing secrets.
5. Optional storage choices can append exports to a shell env file or write a private Codex env file such as `~/.codex/agent-telegram-notifier.env`; only use those after explicit user confirmation.

After setup, check configuration without sending:

```bash
python3 scripts/send_telegram.py --check-config
```

Then send a test:

```bash
python3 scripts/send_telegram.py "Telegram notifier test from Codex."
```

Do not ask users to paste the bot token into chat unless there is no safer option. If the user does paste it, recommend rotating the token with `@BotFather` after setup.

## Automation Environment

Make sure `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are available to the environment that runs Codex or the automation, not only the current shell. GUI apps and scheduled jobs may need a restart, `launchctl setenv`, or an explicit env-file source step before they inherit newly added variables.

## Notification Style

Send one final message after the work is done, whether the result is success, partial, or failed. Keep the message plain text and mobile-readable:

```text
Weekly inbox triage
Status: success

- Reviewed new mail since last run.
- Found 3 items needing replies.
- Drafted suggested responses in the thread.

Next step: Review the drafts before sending.
```

Default to concise summaries. Avoid raw private content, long excerpts, credentials, tokens, and unnecessary local paths. Use "No action needed." when there is no follow-up.

## Sending

Use the bundled sender script:

```bash
python3 /path/to/agent-telegram-notifier/scripts/send_telegram.py "message text"
```

For multi-line messages, pipe text on stdin:

```bash
printf '%s\n' "Title" "Status: success" "" "- Done" "" "Next step: No action needed." \
  | python3 /path/to/agent-telegram-notifier/scripts/send_telegram.py
```

The script sends Telegram `sendMessage` requests, validates required environment variables, retries brief transient failures, and splits long messages into safe chunks by default. Telegram text messages are limited to 4096 characters; use `--no-split` if the caller should fail instead of splitting.

## Automation Prompts

When creating or updating a recurring automation, include an explicit final notification instruction:

```text
After the task is complete, use $agent-telegram-notifier to send me one concise Telegram summary with title, status, key findings, and next step. Send the notification even if the task partially fails.
```

If Telegram delivery fails, preserve the underlying task result and report the notification failure locally.
