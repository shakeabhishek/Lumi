"""Standalone face demo — no audio or LLM needed.

Run: uv run python scripts/face_demo.py
     uv run python scripts/face_demo.py --theme vector
     uv run python scripts/face_demo.py --theme terminal

Controls:
  SPACE    — cycle IDLE → LISTEN → THINK → SPEAK → IDLE
  T        — cycle through pixel / vector / terminal themes
  Q / Esc  — quit
"""

import sys

import pygame

from lumi.hardware.display import make_display
from lumi.runtime.state_machine import LumiState, StateMachine
from lumi.ui.face.engine import FaceEngine

STATES = [LumiState.IDLE, LumiState.LISTEN, LumiState.THINK, LumiState.SPEAK]
THEMES = ["vector", "terminal", "pixel"]  # terminal is the cute bear, not ASCII boxes


def _build_face(theme: str, color: str | None, w: int = 480, h: int = 320) -> tuple[object, FaceEngine, StateMachine]:
    display = make_display(w, h)
    sm = StateMachine()
    face = FaceEngine(display=display, theme=theme, color=color)
    sm.on_state_change(face.set_state)
    return display, face, sm


def main(theme: str = "vector", color: str | None = None) -> None:
    if theme not in THEMES:
        print(f"Unknown theme '{theme}'. Choose from: {', '.join(THEMES)}")
        sys.exit(1)

    theme_idx = THEMES.index(theme)
    display, face, sm = _build_face(THEMES[theme_idx], color)

    state_idx = 0
    sm.transition(STATES[0])

    clock = pygame.time.Clock()
    print("Face demo running.")
    print("  SPACE  — cycle state")
    print("  T      — cycle theme (pixel / vector / terminal)")
    print("  Q/Esc  — quit")
    print(f"\nTheme: {THEMES[theme_idx].upper()}  |  State: {STATES[0].value.upper()}")

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                display.close()
                sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_q, pygame.K_ESCAPE):
                    display.close()
                    sys.exit()
                if event.key == pygame.K_SPACE:
                    state_idx = (state_idx + 1) % len(STATES)
                    sm.transition(STATES[state_idx])
                    print(f"Theme: {THEMES[theme_idx].upper()}  |  State: {STATES[state_idx].value.upper()}")
                if event.key == pygame.K_t:
                    display.close()
                    theme_idx = (theme_idx + 1) % len(THEMES)
                    display, face, sm = _build_face(THEMES[theme_idx], color)
                    sm.transition(STATES[state_idx])
                    print(f"Theme: {THEMES[theme_idx].upper()}  |  State: {STATES[state_idx].value.upper()}")

        face.show()
        clock.tick(30)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--theme", default="vector", choices=THEMES)
    parser.add_argument("--color", default=None, help="Foreground hex color, e.g. #FF6B6B")
    args = parser.parse_args()
    main(args.theme, args.color)
