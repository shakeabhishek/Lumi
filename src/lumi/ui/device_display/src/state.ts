/**
 * Device-display state hook.
 *
 * Subscribes to `/device-display/events` via Server-Sent Events. The
 * backend pushes one JSON frame per LumiState transition + periodic
 * widget-bar updates (weather, CPU). Until the SSE endpoint is live,
 * `connected` stays false and the App falls back to a local demo cycle.
 *
 * Wire format (per SSE `data:` line):
 *   { "state": "idle" | "listen" | "think" | "speak",
 *     "style": "pixel" | "vector" | "terminal" | "sprite",
 *     "theme": "default" | "sunset" | ...,
 *     "statusText": "Connected to cloud",
 *     "spritePack": "cat",
 *     "weather": { "tempC": 22, "condition": "sunny" } | null,
 *     "cpuPct": 45 }
 */

import { useEffect, useState } from 'react';

export type FaceStyle = 'pixel' | 'vector' | 'terminal' | 'sprite';
export type FaceState = 'idle' | 'listen' | 'think' | 'speak';
export type ColorTheme =
  | 'default' | 'sunset' | 'ocean' | 'forest' | 'sakura'
  | 'mint'    | 'lavender' | 'monochrome';

export interface WeatherSnapshot {
  tempC: number;
  condition: 'sunny' | 'cloudy' | 'rainy' | 'snowy' | 'clear-night';
  location?: string;
}

export interface DeviceState {
  connected: boolean;
  state: FaceState;
  style: FaceStyle;
  theme: ColorTheme;
  statusText: string;
  spritePack?: string;
  weather: WeatherSnapshot | null;
  cpuPct: number;
  memPct: number;
  cpuTempC: number;
  volume: number;
  micMuted: boolean;
}

const INITIAL: DeviceState = {
  connected: false,
  state: 'idle',
  style: 'pixel',
  theme: 'default',
  statusText: 'Standalone preview',
  weather: null,
  cpuPct: 0,
  memPct: 0,
  cpuTempC: 0,
  volume: 50,
  micMuted: false,
};

export function useDeviceState(): DeviceState {
  const [state, setState] = useState<DeviceState>(INITIAL);

  useEffect(() => {
    let source: EventSource | null = null;
    try {
      source = new EventSource('/device-display/events');
      source.onmessage = (evt) => {
        try {
          const payload = JSON.parse(evt.data);
          setState((prev) => ({ ...prev, ...payload, connected: true }));
        } catch {
          // ignore malformed payloads — keep last good state.
        }
      };
      source.onerror = () => {
        // Backend not running or endpoint not yet implemented — leave
        // connected=false so App's local demo cycle takes over.
        setState((prev) => ({ ...prev, connected: false }));
      };
    } catch {
      // EventSource unsupported (very old browsers). Stay in demo mode.
    }
    return () => source?.close();
  }, []);

  // Promote `data-theme` onto <html> so the CSS variable overrides
  // cascade into `body, #root` (where index.css paints the gradient).
  // If we only set it on the App wrapper, :root would still hold the
  // default palette and the background wouldn't repaint.
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', state.theme);
  }, [state.theme]);

  return state;
}
