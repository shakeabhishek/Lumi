// Lumi weather plugin — registers a `get_weather` tool that calls OpenWeatherMap.
//
// API key is read from the OPENWEATHERMAP_API_KEY environment variable. The
// gateway launches plugins inheriting its env; the Lumi `lumi-up.sh`
// orchestrator exports the key into the gateway's env from the OS keychain
// at startup (see scripts/lumi-up.sh).

import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

const getWeatherTool = {
  name: "get_weather",
  label: "Get Weather",
  description:
    "Get current weather conditions for a city or location. Returns temperature " +
    "(°C), feels-like, humidity, conditions, and wind speed.",
  parameters: {
    type: "object",
    additionalProperties: false,
    properties: {
      location: {
        type: "string",
        description: "City name, optionally with country, e.g. 'London' or 'Tokyo, JP'",
      },
    },
    required: ["location"],
  },
  execute: async (_toolCallId, rawParams) => {
    const location = String(rawParams?.location ?? "").trim();
    if (!location) {
      return { text: "Missing required 'location' parameter." };
    }
    const key = process.env.OPENWEATHERMAP_API_KEY || "";
    if (!key) {
      return {
        text:
          "OPENWEATHERMAP_API_KEY is not set in the gateway environment. " +
          "Run `lumi keys set openweathermap_api_key` and restart lumi-up.sh.",
      };
    }
    const url = new URL("https://api.openweathermap.org/data/2.5/weather");
    url.searchParams.set("q", location);
    url.searchParams.set("appid", key);
    url.searchParams.set("units", "metric");
    try {
      const res = await fetch(url, { signal: AbortSignal.timeout(10_000) });
      if (res.status === 404) {
        return { text: `Couldn't find a location called "${location}".` };
      }
      if (!res.ok) {
        return { text: `Weather lookup failed: HTTP ${res.status}` };
      }
      const d = await res.json();
      return {
        json: {
          location: d?.name,
          temperature_c: d?.main?.temp,
          feels_like_c: d?.main?.feels_like,
          humidity_pct: d?.main?.humidity,
          conditions: d?.weather?.[0]?.description,
          wind_mps: d?.wind?.speed,
        },
      };
    } catch (err) {
      return { text: `Weather lookup failed: ${String(err?.message ?? err)}` };
    }
  },
};

export default definePluginEntry({
  id: "lumi-weather",
  name: "Lumi Weather Plugin",
  description: "Registers get_weather backed by OpenWeatherMap",
  register(api) {
    api.registerTool(getWeatherTool, { names: ["get_weather"] });
  },
});
