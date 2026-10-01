"""에이전트가 주고받는 데이터 형식.

모든 모듈(Planner, Executor, Observer, Replanner, Reporter)이 이 파일의
클래스만 주고받는다. 모션 이름이나 스테이션 이름이 바뀌어도 이 파일은
바뀌지 않도록, 이름은 전부 문자열로 둔다.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional

# ---------------------------------------------------------------- 액션

ActionType = Literal["observe", "move_rail", "act", "wait"]
ObserveTarget = Literal["camera", "sensors", "thermal"]

# 서버 응답을 에이전트가 구분해서 다룰 수 있게 분류한 오류 종류.
# 파이2 README: 400=명령이 잘못됨, 409=이동 중, 422=입력 검증, 503=하드웨어 없음
ErrorKind = Literal[
    "bad_request",      # 400/404 - 명령 자체가 잘못됨 -> 계획 수정
    "conflict",         # 409 - 원인을 구분할 수 없는 충돌 -> 사람에게 확인
    "busy",             # 409 - 레일이 이미 이동 중 -> 잠시 후 재시도
    "interrupted",      # 409 - 사람이 이동을 멈춤 -> 중단
    "stale_station",    # 409 - 재보정으로 스테이션 좌표 무효 -> 중단
    "invalid",          # 422 - 입력값 검증 실패
    "hw_unavailable",   # 503 - 하드웨어 미연결
    "not_implemented",  # 501 - 서버에 아직 없는 기능 (파이1 팔)
    "interlock",        # 에이전트가 막음 - 팔이 안전 자세가 아닌데 레일 이동 요청
    "declined",         # 되돌릴 수 없는 동작을 사람이 승인하지 않음
    "timeout",          # 응답 대기 초과 - 실제로 움직였는지 알 수 없음 -> 중단
    "unreachable",      # 서버에 연결 불가
    "unknown",
]


@dataclass
class Action:
    """계획의 한 줄.

    type 별 의미:
      move_rail : target = 스테이션 이름 (예: "시약존"). mm 값은 쓰지 않는다.
      act       : name   = ACT 모션 이름 (예: "grasp_reagent")
      observe   : target = "camera" | "sensors" | "thermal"
      wait      : params = {"seconds": 3}
    """
    id: int
    type: ActionType
    name: str
    target: Optional[str] = None
    expect: Optional[str] = None      # 성공 조건 문장. Observer 가 이걸로 판단한다
    irreversible: bool = False        # 시약 투입 등 되돌릴 수 없는 동작
    params: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------- 실행 결과

@dataclass
class ExecResult:
    """실행기가 '끝났는가'. 작업이 '성공했는가'는 Observer 가 따로 판단한다."""
    ok: bool
    http_status: Optional[int] = None
    error_kind: Optional[ErrorKind] = None
    detail: str = ""
    duration_s: float = 0.0


# ---------------------------------------------------------------- 관측

@dataclass
class Observation:
    timestamp: float
    ph: Optional[float] = None
    ec: Optional[float] = None
    sensors_stale: bool = False       # True 면 ph/ec 를 판단에 쓰지 않는다
    thermal_rois: dict[str, Any] = field(default_factory=dict)
    image_jpeg: Optional[bytes] = field(default=None, repr=False)
    image_note: Optional[str] = None  # 카메라 해석 결과(색, 탁도, 파지 여부). Observer 가 채움
    errors: list[str] = field(default_factory=list)  # 읽기에 실패한 항목


@dataclass
class Judgement:
    status: Literal["success", "retry", "replan", "abort"]
    reason: str                       # 보고서의 '판단 근거'가 된다


@dataclass
class LogEntry:
    action: Action
    result: ExecResult
    observation: Optional[Observation]
    judgement: Judgement


# ---------------------------------------------------------------- 상태

@dataclass
class AgentState:
    goal: str
    status: Literal["planning", "running", "finished", "aborted"] = "planning"
    remaining: list[Action] = field(default_factory=list)
    done: list[Action] = field(default_factory=list)
    last_observation: Optional[Observation] = None
    retries: dict[int, int] = field(default_factory=dict)   # 액션 id -> 재시도 횟수
    log: list[LogEntry] = field(default_factory=list)       # 보고서 재료

    # 안전 상태 (파이1/파이2가 서로를 모르므로 에이전트가 들고 있어야 한다)
    arm_safe: bool = True                                   # 레일을 움직여도 되는 팔 자세인가
    rail_station: Optional[str] = None
    allowed_stations: list[str] = field(default_factory=list)

    abort_reason: Optional[str] = None
    replans: int = 0                                        # 재계획 횟수 (무한 반복 방지용)

    def new_id(self) -> int:
        """재계획으로 액션을 끼워 넣을 때 쓰는, 겹치지 않는 id."""
        ids = [a.id for a in self.remaining + self.done] + [e.action.id for e in self.log]
        return max(ids, default=0) + 1

    def record(self, action: Action, result: ExecResult,
               obs: Optional[Observation], judgement: Judgement) -> None:
        self.log.append(LogEntry(action, result, obs, judgement))
        if obs is not None:
            self.last_observation = obs

    def to_dict(self) -> dict[str, Any]:
        """JSON 으로 내보내기(UI·보고서용). 이미지 바이트는 뺀다."""
        return _strip_bytes(asdict(self))


def _strip_bytes(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_bytes(v) for k, v in obj.items()
                if not isinstance(v, (bytes, bytearray))}
    if isinstance(obj, list):
        return [_strip_bytes(v) for v in obj]
    return obj
