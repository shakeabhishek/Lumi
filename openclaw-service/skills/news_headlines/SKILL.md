---
name: news_headlines
description: Read the top headlines from a public news source (RSS, no account required)
---

Fetch the latest top headlines from a curated public RSS feed and read 3-5 of them aloud.
No API key, no personal data sent.

## How to use this skill

Make a GET request to one of these public RSS feeds (pick based on user's request, default to BBC):
- BBC World:     `https://feeds.bbci.co.uk/news/world/rss.xml`
- BBC Tech:      `https://feeds.bbci.co.uk/news/technology/rss.xml`
- NPR top:       `https://feeds.npr.org/1001/rss.xml`
- Hacker News:   `https://news.ycombinator.com/rss`
- Reuters world: `https://feeds.reuters.com/Reuters/worldNews`

Parse the XML and extract the first 3-5 `<title>` elements from `<item>` blocks. Ignore items without titles.

## Response format

Lead with a one-line intro ("Here are today's top headlines from BBC World:") then list the headlines as numbered items, separated by a brief pause. Keep each headline verbatim — do not summarise or editorialise.

Example:
> Here are today's top headlines from BBC World.
> One. EU agrees emergency climate package.
> Two. Pacific summit closes with surprise trade deal.
> Three. Mars sample-return mission delayed two years.

## Edge cases

- If the feed returns no items, say "There don't seem to be any headlines available right now."
- If a specific source was requested but not configured, fall back to BBC World and mention the fallback.

## Privacy notes

RSS feeds are anonymous reads — the server only sees an unauthenticated GET. The user's name, location, and other context never leave the device.
