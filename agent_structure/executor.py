"""액션 하나를 실행하고, 그 결과로 안전 상태(arm_safe, rail_station)를 갱신한다.

파이1(팔)과 파이2(레일)는 서로의 상태를 모른다. 서버 어디에도 동시 동작 방지가
없으므로 충돌 방지는 여기서 에이전트가 직접 한다. (프롬프트가 아니라 코드로 강제)

규칙
  1. 레일 이동은 state.arm_safe 가 참일 때만 호출한다. 아니면 서버를 부르지 않고
     error_kind="interlock" 으로 돌려준다.
  2. act 는 시작 전에 arm_safe=False 로 둔다. 정상 종료하고 그 모션이 ends_safe 일
     때만 True 가 된다. 실패하면 팔 자세를 알 수 없으므로 False 로 남는다.
  3. irreversible 액션은 confirm 콜백이 승인해야만 실행한다. 콜백이 없으면 거부.
  4. 레일 이동이 timeout 이면 실제 위치를 알 수 없으므로 rail_station 을 비운다.
"""
from __future__ import annotations

from typing import Callable, Optional

from . import config
from .state import Action, AgentState, ExecResult
from .tools import Toolbox


class Executor:
    def __init__(self, toolbox: Toolbox,
                 confirm: Optional[Callable[[Action], bool]] = None):
        self.tools = toolbox
        self.confirm = confirm

    def execute(self, state: AgentState, action: Action) -> ExecResult:
        if action.irreversible and not (self.confirm and self.confirm(action)):
            return ExecResult(ok=False, error_kind="declined",
                              detail=f"되돌릴 수 없는 동작이 승인되지 않음: {action.name}")

        if action.type == "move_rail" and not state.arm_safe:
            return ExecResult(ok=False, error_kind="interlock",
                              detail="팔이 안전 자세가 아니라 레일 이동을 막음")

        if action.type == "act":
            motion = config.AVAILABLE_ACTIONS.get(action.name)
            if motion is None:
                return ExecResult(ok=False, error_kind="bad_request",
                                  detail=f"목록에 없는 모션: {action.name}")
            state.arm_safe = False                      # 움직이는 동안은 안전하지 않다
            result = self.tools.execute(action)
            state.arm_safe = bool(result.ok and motion.ends_safe)
            return result

        result = self.tools.execute(action)
        if action.type == "move_rail":
            if result.ok:
                state.rail_station = action.target
            elif result.error_kind == "timeout":
                state.rail_station = None               # 어디에 있는지 모른다
        return result
