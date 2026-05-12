"""Skill base types — shared by native skills and the router."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class SkillResult:
    text: str
    handled: bool = field(default=True)


class NativeSkill(ABC):
    @abstractmethod
    def matches(self, transcript: str) -> bool: ...

    @abstractmethod
    def execute(self, transcript: str) -> SkillResult: ...
