---
name: wikipedia_lookup
description: Look up a topic on Wikipedia and return a concise summary
---

Fetch a summary of the requested topic from Wikipedia using the Wikimedia REST API.

## How to use this skill

Make a GET request to:
```
https://en.wikipedia.org/api/rest_v1/page/summary/{topic}
```

Replace `{topic}` with a URL-encoded version of the topic (e.g. "Alan_Turing", "quantum_computing").

No API key required.

## Response format

Return the `extract` field from the response — the plain-text summary Wikipedia provides.
Trim it to the first 2–3 sentences if it is very long.

Introduce it naturally: "Here's what Wikipedia says about [topic]: ..."

## Disambiguation and errors

- If the API returns a disambiguation page (type: "disambiguation"), ask the user to be more specific.
- If the topic is not found (404), say you couldn't find a Wikipedia article for that topic and suggest an alternate search term.
- Do not fabricate information. If you can't find it, say so.

## Privacy

This skill makes an outbound request to en.wikipedia.org. No user data is included in the request — only the topic name.
