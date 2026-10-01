"""mock 도구만으로 state.py / tools.py 가 맞물려 도는지 확인한다.

실행 (agent 폴더의 상위 폴더에서):  python -m agent.smoke_test
"""
import json

from .state import Action, AgentState, Judgement
from .tools import MockPi1, MockPi2, Toolbox


def main() -> None:
    pi1 = MockPi1(fail={"grasp_reagent": 1})        # 첫 시도는 실패하게 함
    pi2 = MockPi2()
    tb = Toolbox(pi1, pi2, sleep=lambda s: None)

    problems = tb.preflight()
    print("preflight:", problems or "OK", "| stations:", tb.allowed_stations)

    state = AgentState(goal="smoke test", allowed_stations=tb.allowed_stations)
    state.remaining = [
        Action(1, "observe", "초기 상태 확인", target="camera"),
        Action(2, "move_rail", "시약 보관대로 이동", target="시약존"),
        Action(3, "act", "grasp_reagent", expect="그리퍼에 시약병이 잡혀 있다"),
        Action(4, "move_rail", "없는 곳으로 이동", target="화성"),
    ]

    while state.remaining:
        act = state.remaining.pop(0)
        res = tb.execute(act)
        obs = tb.observe(("sensors", "thermal")) if res.ok else None
        verdict = Judgement("success" if res.ok else "abort",
                            f"{res.error_kind or 'ok'} {res.detail}".strip())
        state.record(act, res, obs, verdict)
        print(f"[{act.id}] {act.type:9} {act.name:16} ok={res.ok} {res.error_kind or ''}")

    print(json.dumps(state.to_dict()["log"][1], ensure_ascii=False, indent=2)[:400])


if __name__ == "__main__":
    main()
