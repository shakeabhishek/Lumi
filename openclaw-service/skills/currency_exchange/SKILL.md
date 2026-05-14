---
name: currency_exchange
description: Convert between currencies at live exchange rates
---

Convert an amount from one currency to another using the public exchangerate.host API.
No API key needed and no personal data leaves the device (request is just amount + currency codes).

## How to use this skill

Make a GET request to:
```
https://api.exchangerate.host/convert?from={from_code}&to={to_code}&amount={amount}
```

Parse the user's request for:
- `from_code` — three-letter ISO currency code (USD, EUR, GBP, JPY, ...)
- `to_code` — three-letter ISO currency code
- `amount` — numeric amount; default to 1 if unspecified

The response is JSON. Read `result` for the converted value.

## Response format

Report the converted value in one warm, natural sentence with two decimal places.

Example: "100 US dollars is about 92.40 euros right now."
Example: "1 British pound is about 187.30 Japanese yen at today's rate."

If the user gave no amount, phrase the answer as "1 X is about N Y".

## Error handling

- If either currency code is not recognised, ask the user to clarify which currencies they mean.
- If the network is unavailable, say "I couldn't reach the exchange-rate service right now — try again in a moment."
- Never make up rates. Always use the API value.

## Privacy notes

The request only contains currency codes and a number. No user identity, location, or context is sent.
