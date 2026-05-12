---
name: timer
description: Set a countdown timer for a specified duration
---

Set a countdown timer for the duration requested by the user.

## Parsing duration

Parse natural language durations:
- "5 minutes" → 300 seconds
- "30 seconds" → 30 seconds
- "1 hour" → 3600 seconds
- "1 hour 30 minutes" → 5400 seconds
- "half an hour" → 1800 seconds

## How to set the timer

Use the built-in timer or scheduling functionality to count down the requested duration.
Record the start time and the target end time.

Confirm to the user: "Timer set for 5 minutes. I'll let you know when it's done."

When the timer fires, notify the user with a gentle message:
"Your 5-minute timer is up."

## Edge cases

- If the duration is ambiguous (e.g. "a bit"), ask for clarification.
- Maximum timer duration: 24 hours. If the user requests longer, suggest a reminder instead.
- If the user says "cancel timer" or "stop the timer", cancel any active countdown.
