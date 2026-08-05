"""Shared gesture vocabulary.

V1 gesture set (from CLAUDE.md):
  WAVE        — wake / greet
  OPEN_PALM   — pause / stop talking
  THUMBS_UP   — yes / accept
  THUMBS_DOWN — no / reject
  FIST        — cancel / dismiss

Detection itself runs out-of-process in vision-worker/ (MediaPipe requires
protobuf 4.x, incompatible with this project's protobuf 7.x via chromadb)
— this enum exists so ui/web/routes/context_api.py can validate incoming
/api/gesture payloads against a single source of truth. vision-worker
keeps its own local copy (see vision-worker/src/lumi_vision_worker/
classify.py) since that process can't import this `lumi` package at all;
the two are kept in sync by convention and validated at the wire boundary
(a plain string over HTTP), not by sharing a Python type.
"""

from __future__ import annotations

from enum import Enum


class GestureType(Enum):
    NONE = "none"
    WAVE = "wave"
    OPEN_PALM = "open_palm"
    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"
    FIST = "fist"
