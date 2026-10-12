# cognition/proactive/stance_selector.py
"""姿态选择器 —— 决定主动行为以什么语气表达"""

from enum import Enum
from collections import deque
import random

class Stance(Enum):
    CURIOSITY = "curiosity"
    VULNERABILITY = "vulnerability"
    SKEPTICISM = "skepticism"
    REFLECTION = "reflection"

class StanceResult:
    def __init__(self, stance: Stance):
        self.stance = stance

class StanceSelector:
    def __init__(self, creativity: float = 0.3):
        self.creativity = creativity
        self._recent_stances: deque = deque(maxlen=3)

    def select(self, epistemic_state, tension_type: str = "",
               topic_trap: bool = False) -> StanceResult:
        """根据认知状态和上下文选择姿态（内部决策用，不输出给LLM）"""
        from .epistemic_monitor import EpistemicState as ES

        if topic_trap:
            stance = Stance.CURIOSITY if random.random() > 0.4 else Stance.VULNERABILITY
        elif epistemic_state in (ES.VOID, ES.FRAGMENTARY):
            stance = Stance.CURIOSITY if random.random() > 0.3 else Stance.VULNERABILITY
        elif tension_type == "conflict":
            stance = Stance.SKEPTICISM
        elif tension_type in ("pattern", "inconsistency"):
            stance = Stance.REFLECTION
        else:
            stance = Stance.CURIOSITY

        # 避免连续重复姿态
        if stance in self._recent_stances and random.random() < self.creativity:
            alternatives = [s for s in Stance if s != stance]
            stance = random.choice(alternatives)

        self._recent_stances.append(stance)
        return StanceResult(stance=stance)