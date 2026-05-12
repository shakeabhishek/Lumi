"""Speaker verification — recognizes the device owner.

V1 plan (per CLAUDE.md):
  - 5 enrollment prompts during onboarding
  - Resemblyzer or SpeechBrain ECAPA-TDNN computes a ~192-d embedding
  - Embedding stored locally; new clips compared by cosine similarity

Week 1 ships a stub so the runtime can be wired without blocking on the
enrollment UX. The stub trusts everyone.
"""

from __future__ import annotations

import numpy as np


class VoiceID:
    def is_owner(self, audio: np.ndarray, sample_rate: int) -> bool:  # noqa: ARG002
        return True
