"""메인 루프: 계획 -> 실행 -> 관찰 -> 판단 -> (다음 / 재시도 / 재계획 / 중단) -> 보고서."""
from __future__ import annotations

import time
from typing import Callable, Optional

from . import config
from .executor import Executor
from .observer import Observer
from .planner import validate_plan
from .replanner import Replanner
from .reporter import Reporter
from .state import Action, AgentState, ExecResult, Judgement, Observation
from .tools import Toolbox


def _observe_targets(action: Action):
    if action.type == "observe":
        return (action.target,) if action.target in config.OBSERVE_TARGETS else config.OBSERVE_TARGETS
    if action.type == "act":
        return config.OBSERVE_TARGETS      # 동작 직후에는 카메라·센서를 모두 읽는다
    return None                            # 레일 이동, 대기는 관측하지 않는다


class Agent:
    def __init__(self, toolbox: Toolbox, planner, executor: Executor,
                 observer: Observer, replanner: Replanner, reporter: Reporter, *,
                 max_retries: int = config.MAX_RETRIES,
                 max_replans: int = config.MAX_REPLANS,
                 max_steps: int = config.MAX_STEPS,
                 sleep: Callable[[float], None] = time.sleep,
                 on_step: Optional[Callable[[AgentState, Action, ExecResult, Judgement], None]] = None):
        self.tools, self.planner, self.executor = toolbox, planner, executor
        self.observer, self.replanner, self.reporter = observer, replanner, reporter
        self.max_retries, self.max_replans, self.max_steps = max_retries, max_replans, max_steps
        self.sleep, self.on_step = sleep, on_step

    def run(self, goal: str):
        state = AgentState(goal=goal)

        problems = self.tools.preflight()
        if problems:
            return self._finish(state, abort="시작 전 점검 실패: " + "; ".join(problems))
        state.allowed_stations = list(self.tools.allowed_stations)

        plan = self.planner.plan(goal, state)
        errors = validate_plan(plan, state.allowed_stations)
        if errors:
            return self._finish(state, abort="계획 검증 실패: " + "; ".join(errors))
        state.remaining = plan
        state.status = "running"

        steps = 0
        while state.remaining:
            steps += 1
            if steps > self.max_steps:
                return self._finish(state, abort=f"최대 스텝({self.max_steps}) 초과")

            action = state.remaining.pop(0)
            result = self.executor.execute(state, action)

            targets = _observe_targets(action) if result.ok else None
            obs: Optional[Observation] = self.tools.observe(targets) if targets else None

            judgement = self.observer.check(state, action, result, obs)
            state.record(action, result, obs, judgement)
            if self.on_step:
                self.on_step(state, action, result, judgement)

            if judgement.status == "success":
                state.done.append(action)

            elif judgement.status == "retry":
                n = state.retries.get(action.id, 0) + 1
                if n > self.max_retries:
                    return self._finish(state, abort=f"[{action.id}] 재시도 {self.max_retries}회 초과: {judgement.reason}")
                state.retries[action.id] = n
                self.sleep(config.RETRY_WAIT_S)
                state.remaining.insert(0, action)

            elif judgement.status == "replan":
                state.replans += 1
                if state.replans > self.max_replans:
                    return self._finish(state, abort=f"재계획 {self.max_replans}회 초과: {judgement.reason}")
                new = self.replanner.replan(state, action, judgement)
                if new is None:
                    return self._finish(state, abort=f"[{action.id}] 복구할 수 없음: {judgement.reason}")
                errors = validate_plan(new, state.allowed_stations)
                if errors:
                    return self._finish(state, abort="재계획 검증 실패: " + "; ".join(errors))
                state.remaining = new

            else:  # abort
                return self._finish(state, abort=f"[{action.id}] {judgement.reason}")

        return self._finish(state)

    def _finish(self, state: AgentState, abort: Optional[str] = None):
        if abort:
            state.status, state.abort_reason = "aborted", abort
        else:
            state.status = "finished"
        return state, self.reporter.write(state)
