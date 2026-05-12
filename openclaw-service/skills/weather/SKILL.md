---
name: weather
description: Get current weather conditions for any city or location
---

Fetch and report current weather for the requested location using the OpenWeatherMap API.

## How to use this skill

Make a GET request to:
```
https://api.openweathermap.org/data/2.5/weather?q={location}&appid={OPENWEATHERMAP_API_KEY}&units=metric
```

Replace `{location}` with the city name from the user's request (e.g. "London", "New York", "Tokyo,JP").
Replace `{OPENWEATHERMAP_API_KEY}` with the value of the `OPENWEATHERMAP_API_KEY` environment variable.

## Response format

Report the following in a single warm, natural sentence:
- Current temperature in Celsius (and Fahrenheit if useful)
- Weather description (e.g. "partly cloudy", "light rain")
- Humidity percentage
- Wind speed in km/h

Example: "It's 18°C and partly cloudy in London right now, with 72% humidity and a light breeze at 12 km/h."

## Error handling

- If the location is not found (404), ask the user to clarify the city name.
- If the API key is missing or invalid (401), say the weather skill isn't configured yet and suggest checking the setup.
- Do not expose raw error messages or API keys in your response.
