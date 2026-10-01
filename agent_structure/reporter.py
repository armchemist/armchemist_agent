"""실행 기록으로 보고서를 만든다 (담당 목록 4번).

⚠ 지금은 뼈대다. 로그를 그대로 정리한 dict 를 돌려줄 뿐이고, 화학적 해석이나
  UI 보고서 목업 형식(그래프·판단 근거 문장)은 아직 없다.
"""
from __future__ import annotations

from .state import AgentState


class Reporter:
    def write(self, state: AgentState) -> dict:
        steps = [{
            "id": e.action.id,
            "type": e.action.type,
            "name": e.action.name,
            "target": e.action.target,
            "ok": e.result.ok,
            "error_kind": e.result.error_kind,
            "judgement": e.judgement.status,
            "reason": e.judgement.reason,
        } for e in state.log]
        return {
            "goal": state.goal,
            "status": state.status,
            "abort_reason": state.abort_reason,
            "replans": state.replans,
            "steps": steps,
            "state": state.to_dict(),
        }
