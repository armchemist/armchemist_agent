"""실행 결과를 보고 판단한다 (담당 목록 3번).

⚠ 지금은 뼈대다.
  - 실행기가 실패했을 때: error_kind 별 규칙표로 판단한다 (완성된 부분).
  - 실행기가 성공했을 때: 항상 success. action.expect 를 카메라·센서로 검증하는
    부분은 아직 없다 -> 여기가 3번 작업의 본체.
"""
from __future__ import annotations

from typing import Optional

from .state import Action, AgentState, ExecResult, Judgement, Observation

# 실패 원인 -> 판단. 파이2 README 의 상태 코드 설명을 규칙으로 옮겼다.
_BY_ERROR = {
    "busy": "retry",              # 레일이 이동 중 -> 잠시 후 다시
    "bad_request": "replan",      # 명령이 잘못됨 -> 계획을 고친다
    "invalid": "replan",
    "interlock": "replan",        # 팔이 안전 자세가 아님 -> 접기 모션을 끼워 넣는다
    # 아래는 사람이 봐야 하는 상황이라 재시도하지 않는다
    "interrupted": "abort",
    "stale_station": "abort",
    "conflict": "abort",          # 409 인데 원인을 구분할 수 없음
    "timeout": "abort",           # 움직였는지 알 수 없음
    "hw_unavailable": "abort",
    "unreachable": "abort",
    "not_implemented": "abort",
    "declined": "abort",
    "unknown": "abort",
}


class Observer:
    def check(self, state: AgentState, action: Action, result: ExecResult,
              obs: Optional[Observation]) -> Judgement:
        if not result.ok:
            status = _BY_ERROR.get(result.error_kind or "unknown", "abort")
            return Judgement(status, f"{result.error_kind}: {result.detail}")

        note = ""
        if obs is not None and obs.sensors_stale:
            note = " (센서 값이 오래돼 판단에 쓰지 않음)"
        # TODO(3번): action.expect 를 obs(카메라·센서·열화상)로 검증
        return Judgement("success", "실행기 정상 종료. expect 검증은 아직 없음" + note)
