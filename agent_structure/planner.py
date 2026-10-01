"""계획 만들기.

지금은 FixedPlanner(고정값)만 있다. LLM Planner 는 같은 인터페이스
`plan(goal, state) -> list[Action]` 로 만들어 교체한다.

validate_plan 은 LLM 이 만든 계획이든 재계획 결과든 실행 전에 반드시 통과시킨다.
LLM 이 목록에 없는 모션이나 스테이션을 만들어내도 실행되기 전에 걸러진다.
"""
from __future__ import annotations

from typing import Iterable, Optional

from . import config
from .state import Action, AgentState


def validate_plan(actions: Iterable[Action],
                  allowed_stations: Optional[list[str]] = None) -> list[str]:
    """문제 목록을 돌려준다. 비어 있으면 통과."""
    errors: list[str] = []
    seen: set[int] = set()
    for a in actions:
        tag = f"[{a.id}] {a.type}/{a.name}"
        if a.id in seen:
            errors.append(f"{tag}: id 중복")
        seen.add(a.id)
        if a.type == "act":
            if a.name not in config.AVAILABLE_ACTIONS:
                errors.append(f"{tag}: 목록에 없는 모션")
        elif a.type == "move_rail":
            if not a.target:
                errors.append(f"{tag}: target(스테이션 이름) 없음")
            elif allowed_stations and a.target not in allowed_stations:
                errors.append(f"{tag}: 허용되지 않은 스테이션 '{a.target}'")
        elif a.type == "observe":
            if a.target not in config.OBSERVE_TARGETS:
                errors.append(f"{tag}: observe target 은 {config.OBSERVE_TARGETS} 중 하나")
        elif a.type == "wait":
            pass
        else:
            errors.append(f"{tag}: 알 수 없는 type")
    return errors


class FixedPlanner:
    """문서 3번의 8단계 예시를 그대로 옮긴 고정 계획 (목표 문장은 쓰지 않는다)."""

    def __init__(self, skip_stow: bool = False):
        # skip_stow=True 는 인터락 → 재계획 경로를 시험하기 위한 옵션
        self.skip_stow = skip_stow

    def plan(self, goal: str, state: AgentState) -> list[Action]:
        steps = [
            Action(0, "observe", "시약병과 반응 용기 상태 확인", target="camera",
                   expect="시약병과 반응 용기가 보인다"),
            Action(0, "move_rail", "시약 보관대로 이동", target=config.STATION_REAGENT),
            Action(0, "act", "grasp_reagent", expect="그리퍼에 시약병이 잡혀 있다"),
            Action(0, "observe", "파지 결과 확인", target="camera",
                   expect="시약병이 보관대에서 사라졌고 그리퍼가 차 있다"),
            Action(0, "move_rail", "작업 위치로 이동", target=config.STATION_WORK),
            Action(0, "act", "pour_reagent", expect="용기에 시약이 들어갔다",
                   irreversible=True),
        ]
        if not self.skip_stow:
            steps.append(Action(0, "act", "stow_arm", expect="팔이 안전 자세다"))
        steps += [
            Action(0, "move_rail", "시약 보관대로 복귀", target=config.STATION_REAGENT),
            Action(0, "observe", "결과 확인", target="sensors",
                   expect="pH, 전도도가 읽힌다"),
        ]
        for i, a in enumerate(steps, start=1):
            a.id = i
        return steps
