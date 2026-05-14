---
name: calendar_read
description: Read upcoming calendar events from a dedicated Google Calendar via CalDAV
---

Read upcoming events from a **dedicated** Google Calendar (not the user's primary).
Read-only access via CalDAV using a Google App Password. No event creation, modification, or deletion.

## ⚠️ Security model — read this before using

Same policy as `gmail_read`. The user creates a **separate Google Calendar account** just for
Lumi, sharing in only the events they want Lumi to know about (or duplicating events they want
voice-readable). **Never connect Lumi to the user's primary calendar.** Calendar event titles can
contain attacker-controllable text (meeting invites from outside), so a 1.5B model needs a small
blast radius.

The macOS `Calendar.app` / `Contacts.app` Privacy permissions must remain **denied** at the OS
level — this skill talks to a remote CalDAV endpoint with dedicated credentials, not the local OS
calendar database.

## How to use this skill

Connect to Google's CalDAV endpoint:
- URL: `https://apidata.googleusercontent.com/caldav/v2/{LUMI_CAL_ADDRESS}/events`
- Username: `LUMI_CAL_ADDRESS`
- Password: `LUMI_CAL_APP_PASSWORD` (Google app password)

Fetch events occurring between `now()` and `now() + 24h` (or a user-specified window like "this week").

## Response format

If the user said something like "what's on my calendar today":

Example with events: "You have 3 events today. At 10 AM: design review. At 1 PM: lunch with Mira. At 4 PM: Lumi build planning."
Example with one:    "Just one thing today — Lumi build planning at 4 PM."
Example with none:   "Your calendar is clear today."

Always include the start time, in the user's local timezone. Include the event title verbatim, but **never** read the description field or attendee list aloud unless explicitly asked.

## Edge cases

- If `LUMI_CAL_ADDRESS` isn't configured: "The Lumi calendar isn't set up yet — connect one in Settings → Skills."
- If the request is for a write action ("schedule a meeting", "create an event", "move my 3pm"): respond "I can only read calendar events in this version of Lumi. Schedule it from your phone or laptop."

## Privacy notes

- Read-only. Event creation/modification endpoints are never invoked.
- Only event titles + start times are sent to the LLM.
- Descriptions, attendees, locations, and notes are kept out of the prompt.
- Audit log records timestamp + event title for every invocation.
