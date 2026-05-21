# Sprite-loop scenes for Lumi's idle display

Drop a folder here with PNG frames and a `manifest.json`. Lumi will play
them as an ambient loop when she's idle on the device display.

## Directory layout

```
sleeping-cat/
    manifest.json
    frame_001.png
    frame_002.png
    frame_003.png
    ...
```

## manifest.json (all keys optional)

```json
{
  "fps": 6,
  "scale": 4,
  "anchor": "center",
  "background": "#0a0e1e"
}
```

- **fps**: how many frames per second to play (default 6)
- **scale**: integer pixel scale-up (default 4 — most sprite art is 16×16
  or 32×32 and looks too small on a 480×320 display)
- **anchor**: "center" | "bottom" | "top" — where to place the sprite
- **background**: hex color for the scene's solid backdrop

## Wiring a downloaded pack

1. Drop files in this directory (e.g. `sleeping-cat/`)
2. Add an entry to `src/lumi/ui/face/idle_scenes.py` in the `SCENES` dict:
   ```python
   "cat-real": lambda: SpriteLoopScene("sleeping-cat"),
   ```
3. Add the option to the dropdown in
   `src/lumi/ui/web/templates/settings/face.html`

## Free sprite sources

- **kenney.nl/assets** — CC0 (public domain), no attribution needed
  - "1-Bit Pack", "Toon Characters", "Pixel Platformer"
- **opengameart.org** — CC0/CC-BY; filter the search by license
- **itch.io** — many CC0/CC-BY free packs; Pixel Frog, Penzilla, MrBubbleWand
  are reliable creators
- **Glitch the Game art dump** (public domain) — softer illustrated style
