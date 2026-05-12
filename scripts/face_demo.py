"""Standalone face demo — no audio or LLM needed.

Run: uv run python scripts/face_demo.py

Controls:
  SPACE — cycle through IDLE → LISTEN → THINK → SPEAK → IDLE
  Q / Esc / close window — quit
"""

import sys

import pygame

from lumi.hardware.display import make_display
from lumi.runtime.state_machine import LumiState, StateMachine
from lumi.ui.face.engine import FaceEngine

STATES = [LumiState.IDLE, LumiState.LISTEN, LumiState.THINK, LumiState.SPEAK]


def main() -> None:
    display = make_display(480, 320)
    sm = StateMachine()
    face = FaceEngine(display=display)
    sm.on_state_change(face.set_state)

    idx = 0
    sm.transition(STATES[0])

    clock = pygame.time.Clock()
    print("Face demo running.")
    print("  SPACE  — cycle state")
    print("  Q/Esc  — quit")
    print(f"\nCurrent state: {STATES[0].value.upper()}")

    while True:
        # Drain events before face.show() so we can intercept SPACE/Q.
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                display.close()
                sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_q, pygame.K_ESCAPE):
                    display.close()
                    sys.exit()
                if event.key == pygame.K_SPACE:
                    idx = (idx + 1) % len(STATES)
                    sm.transition(STATES[idx])
                    print(f"Current state: {STATES[idx].value.upper()}")

        face.show()
        clock.tick(30)


if __name__ == "__main__":
    main()
