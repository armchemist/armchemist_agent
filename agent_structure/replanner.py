"""남은 계획을 고친다 (담당 목록 3번).

⚠ 지금은 규칙 하나뿐이다: 인터락에 걸리면 접기 모션을 끼워 넣고 같은 액션을 다시 시도.
  그 밖의 replan 요청은 None(= 중단)으로 돌려준다. LLM 재계획은 여기에 붙인다.

돌려주는 값은 '새로운 남은 계획 전체'이다. None 이면 에이전트는 중단한다.
"""
from __future__ import annotations

from typing import Optional

from . import config
from .state import Action, AgentState, Judgement


class Replanner:
    def replan(self, state: AgentState, failed: Action,
               judgement: Judgement) -> Optional[list[Action]]:
        last = state.log[-1].result if state.log else None
        if last is not None and last.error_kind == "interlock":
            stow = Action(state.new_id(), "act", config.SAFE_POSE_MOTION,
                          expect="팔이 안전 자세다")
            return [stow, failed] + state.remaining
        return None
