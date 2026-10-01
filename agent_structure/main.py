"""실행 진입점.   python -m agent.main            (mock, 승인 질문 있음)
                 python -m agent.main --yes      (되돌릴 수 없는 동작을 자동 승인)
                 python -m agent.main --skip-stow (인터락 → 재계획 경로 시험)
환경변수 AGENT_PI1 / AGENT_PI2 = mock|real 로 실제 장비를 붙인다 (tools.py 참고).
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .agent import Agent
from .executor import Executor
from .observer import Observer
from .planner import FixedPlanner
from .replanner import Replanner
from .reporter import Reporter
from .tools import make_toolbox


def build_agent(*, confirm, skip_stow=False, on_step=None, sleep=time.sleep) -> Agent:
    tools = make_toolbox()
    return Agent(tools, FixedPlanner(skip_stow=skip_stow), Executor(tools, confirm=confirm),
                 Observer(), Replanner(), Reporter(), sleep=sleep, on_step=on_step)


def _print_step(state, action, result, judgement):
    mark = {"success": "OK ", "retry": "RETRY", "replan": "REPLAN", "abort": "ABORT"}[judgement.status]
    where = action.target or ""
    print(f"  [{action.id:>2}] {mark:6} {action.type:9} {action.name} {where}  <- {judgement.reason}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("goal", nargs="?", default="데모 실험")
    ap.add_argument("--yes", action="store_true", help="되돌릴 수 없는 동작을 묻지 않고 승인")
    ap.add_argument("--skip-stow", action="store_true", help="접기 모션을 뺀 계획 (인터락 시험)")
    ap.add_argument("--out", default="reports")
    args = ap.parse_args(argv)

    def confirm(action):
        if args.yes:
            return True
        return input(f"  되돌릴 수 없는 동작 '{action.name}' 을 실행할까요? [y/N] ").strip().lower() == "y"

    agent = build_agent(confirm=confirm, skip_stow=args.skip_stow, on_step=_print_step)
    print(f"목표: {args.goal}")
    state, report = agent.run(args.goal)
    print(f"결과: {state.status}" + (f" - {state.abort_reason}" if state.abort_reason else ""))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"run_{time.strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"보고서: {path}")
    return 0 if state.status == "finished" else 1


if __name__ == "__main__":
    raise SystemExit(main())
