---
name: gmail_read
description: Read unread email subjects from a dedicated Gmail account via IMAP
---

Read recent unread email subjects from a **dedicated** Gmail account (not the user's primary).
Read-only access via IMAP using a Google App Password. No send, no delete, no draft.

## ⚠️ Security model — read this before using

Lumi's V1 design requires this skill to talk to a **separate Gmail account** the user creates
just for Lumi, with only what they want Lumi to see forwarded into it. **Never connect Lumi to
the user's primary Gmail.** A 1.5B model is not robust to prompt injection in email bodies, so the
blast radius is limited by giving Lumi access only to a curated, low-value inbox.

## How to use this skill

Connect to Gmail's IMAP server using credentials from environment:
- Host: `imap.gmail.com`, port 993, SSL
- Username: `LUMI_GMAIL_ADDRESS`
- App password: `LUMI_GMAIL_APP_PASSWORD` (NOT the account password — generate at https://myaccount.google.com/apppasswords)

Once connected:
1. Select the `INBOX` mailbox.
2. Search for `UNSEEN` messages.
3. Fetch only the `Subject`, `From`, and `Date` headers for the most recent 5 unread.
4. Do NOT fetch message bodies. Subjects are bounded; bodies are not.

## Response format

Summarise in one or two warm sentences.

Example with mail: "You have 3 unread emails. The most recent is from `bookings@hotel.com` — 'Your reservation is confirmed'."
Example with none: "Inbox is clear — no unread messages."

If the user asks for more detail, list at most 5 subjects with their senders. Never read out the body or attachments.

## Error handling

- Auth failure: "I can't reach the Lumi inbox right now — the app password may need to be regenerated."
- Network failure: "I couldn't reach Gmail just now. Try again in a moment."
- Quota: "Gmail is rate-limiting that — try again in a few minutes."

## Privacy notes

- Only headers are fetched. Bodies are never sent to the LLM.
- The IMAP connection is mTLS to imap.gmail.com.
- Every invocation is logged in Lumi's audit log with timestamp + sender + subject (never body).
- Disable any time in Settings → Skills → gmail_read.
