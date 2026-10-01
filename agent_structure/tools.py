"""에이전트의 도구 계층. 실제 장비 호출과 mock 을 같은 인터페이스로 맞춘다.

구성
  Pi2Client / MockPi2 : 고정 파이 (PiSensorServer) - 레일, 열화상, pH/전도도
  Pi1Client / MockPi1 : 레일 위 파이 (PiRobotControl) - 핸디캠, 로봇 팔
  Toolbox             : 두 파이를 묶어 Action 을 실행하고 관측값을 모은다

선택은 환경변수로 한다 (기본은 둘 다 mock).
  AGENT_PI1=mock|real   AGENT_PI2=mock|real
  PI1_URL (기본 http://pi1.local:8000)   PI2_URL (기본 http://pi.local:8000)
  PI1_API_KEY, PI2_API_KEY               -> X-API-Key 헤더

⚠ 서버 응답 중 README 에 모양이 적혀 있지 않은 것(/rail/stations, /rail/where,
  /thermal/rois, 409 의 본문)은 방어적으로 파싱했다. 실제 응답을 확인하고 맞출 것.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable, Iterable, Optional

import requests

from .state import Action, ErrorKind, ExecResult, Observation

DEFAULT_TIMEOUT_S = float(os.getenv("AGENT_HTTP_TIMEOUT_S", "10"))
RAIL_MOVE_TIMEOUT_S = float(os.getenv("AGENT_RAIL_TIMEOUT_S", "120"))  # 이동은 끝나야 응답한다
MAX_WAIT_S = 600.0


# ================================================================ 공통

class ToolError(RuntimeError):
    """읽기 호출이 실패했을 때. 실행 호출은 예외 대신 ExecResult 로 돌려준다."""

    def __init__(self, result: ExecResult):
        super().__init__(f"{result.error_kind}: {result.detail}")
        self.result = result


def _detail_of(resp: requests.Response) -> str:
    try:
        body = resp.json()
        if isinstance(body, dict):
            body = body.get("detail", body)
        return str(body)[:300]
    except ValueError:
        return resp.text[:300]


def _classify(status: int, detail: str) -> ErrorKind:
    d = detail.lower()
    if status in (400, 404):
        return "bad_request"
    if status == 409:
        # 409 는 세 가지 원인이 섞여 있다. 본문 키워드로 구분하되,
        # 구분이 안 되면 'conflict' 로 두고 사람에게 넘긴다 (재시도 금지).
        if any(k in d for k in ("stale", "revalidate", "재등록", "재보정")):
            return "stale_station"
        if any(k in d for k in ("interrupt", "stopped", "중단", "정지")):
            return "interrupted"
        if any(k in d for k in ("moving", "busy", "이동 중", "진행 중")):
            return "busy"
        return "conflict"
    if status == 422:
        return "invalid"
    if status == 501:
        return "not_implemented"
    if status == 503:
        return "hw_unavailable"
    return "unknown"


class _Http:
    def __init__(self, base_url: str, api_key: Optional[str]):
        self.base_url = base_url.rstrip("/")
        self._s = requests.Session()
        if api_key:
            self._s.headers["X-API-Key"] = api_key

    def send(self, method: str, path: str, *, json_body: Any = None,
             timeout: float = DEFAULT_TIMEOUT_S):
        t0 = time.monotonic()
        try:
            r = self._s.request(method, self.base_url + path,
                                json=json_body, timeout=timeout)
        except requests.Timeout as exc:
            # 이동 요청이 타임아웃이면 실제로 움직였는지 알 수 없다.
            return None, ExecResult(ok=False, error_kind="timeout", detail=str(exc),
                                    duration_s=time.monotonic() - t0)
        except requests.RequestException as exc:
            return None, ExecResult(ok=False, error_kind="unreachable", detail=str(exc),
                                    duration_s=time.monotonic() - t0)
        dur = time.monotonic() - t0
        if r.ok:
            return r, ExecResult(ok=True, http_status=r.status_code, duration_s=dur)
        detail = _detail_of(r)
        return r, ExecResult(ok=False, http_status=r.status_code,
                             error_kind=_classify(r.status_code, detail),
                             detail=detail, duration_s=dur)

    def get_json(self, path: str, timeout: float = DEFAULT_TIMEOUT_S) -> Any:
        r, res = self.send("GET", path, timeout=timeout)
        if not res.ok:
            raise ToolError(res)
        try:
            return r.json()
        except ValueError:
            raise ToolError(ExecResult(ok=False, http_status=r.status_code,
                                       error_kind="unknown", detail="JSON 응답이 아님"))


# ================================================================ 파이2 (고정)

class Pi2Client:
    """PiSensorServer. 에이전트에게 노출하는 것만 감쌌다.

    일부러 뺀 것: /rail/move, /rail/move_to, /rail/jog, /rail/calibration/*,
    /rail/set_position, /rail/resume, /rail/stop.
    (README: 보정·디버깅용이거나 사람이 실제 위치를 확인해야 하는 것들)
    """

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        self.http = _Http(base_url or os.getenv("PI2_URL", "http://pi.local:8000"),
                          api_key or os.getenv("PI2_API_KEY"))

    def health(self) -> dict:
        return self.http.get_json("/health")

    def rail_stations(self) -> list[str]:
        """이동 가능한 스테이션 이름. stale 로 표시된 것은 뺀다 (goto 가 409)."""
        data = self.http.get_json("/rail/stations")
        items = data.get("stations", data) if isinstance(data, dict) else data
        names: list[str] = []
        if isinstance(items, dict):
            items = [{"name": k, **(v if isinstance(v, dict) else {})} for k, v in items.items()]
        for it in items or []:
            if isinstance(it, dict):
                if it.get("stale"):
                    continue
                if it.get("name"):
                    names.append(str(it["name"]))
            else:
                names.append(str(it))
        return names

    def rail_where(self) -> Optional[str]:
        data = self.http.get_json("/rail/where")
        if isinstance(data, dict):
            return data.get("station") or data.get("name")
        return str(data) if data else None

    def rail_goto(self, station: str) -> ExecResult:
        _, res = self.http.send("POST", "/rail/goto", json_body={"station": station},
                                timeout=RAIL_MOVE_TIMEOUT_S)
        return res

    def sensors(self) -> dict:
        return self.http.get_json("/sensors")        # {"ph","ec","age_s","stale"}

    def thermal_rois(self) -> Any:
        return self.http.get_json("/thermal/rois")

    def thermal_register_roi(self, name: str, x: int, y: int, w: int, h: int) -> ExecResult:
        _, res = self.http.send("POST", "/thermal/roi",
                                json_body={"x": x, "y": y, "w": w, "h": h, "name": name})
        return res


class MockPi2:
    """장비 없이 루프를 돌리기 위한 가짜. 값은 속성으로 바꿔 가며 시험한다."""

    def __init__(self, stations: Iterable[str] = ("시약존", "비커존", "실린더존", "폐기통")):
        self.stations = list(stations)          # 임시 이름. 실제 스테이션으로 교체할 것
        self.station: Optional[str] = self.stations[0]
        self.ph, self.ec, self.stale = 7.0, 600.0, False
        self.thermal = {"비커": {"mean": 25.0, "min": 24.5, "max": 25.5}}
        self.fail_goto: dict[str, ExecResult] = {}   # 이름 -> 돌려줄 실패 결과
        self.goto_history: list[str] = []

    def health(self) -> dict:
        return {"rail": {"position_known": True}, "sensors": {}, "thermal": {}}

    def rail_stations(self) -> list[str]:
        return list(self.stations)

    def rail_where(self) -> Optional[str]:
        return self.station

    def rail_goto(self, station: str) -> ExecResult:
        if station not in self.stations:
            return ExecResult(ok=False, http_status=404, error_kind="bad_request",
                              detail=f"unknown station {station}")
        if station in self.fail_goto:
            return self.fail_goto[station]
        self.goto_history.append(station)
        self.station = station
        return ExecResult(ok=True, http_status=200, duration_s=0.01)

    def sensors(self) -> dict:
        return {"ph": self.ph, "ec": self.ec, "age_s": 0.1, "stale": self.stale}

    def thermal_rois(self) -> Any:
        return self.thermal

    def thermal_register_roi(self, name: str, x: int, y: int, w: int, h: int) -> ExecResult:
        self.thermal.setdefault(name, {"mean": 25.0, "min": 25.0, "max": 25.0})
        return ExecResult(ok=True, http_status=200)


# ================================================================ 파이1 (레일 위)

class Pi1Client:
    """PiRobotControl. 팔 API 는 아직 501 이라 act 는 호출하지 않고 미구현으로 돌려준다."""

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        self.http = _Http(base_url or os.getenv("PI1_URL", "http://pi1.local:8000"),
                          api_key or os.getenv("PI1_API_KEY"))

    def health(self) -> dict:
        return self.http.get_json("/health")

    def camera_capture(self) -> bytes:
        r, res = self.http.send("GET", "/camera/capture")
        if not res.ok:
            raise ToolError(res)
        return r.content

    def arm_act(self, name: str) -> ExecResult:
        # 팔 API 모양이 정해지면 여기만 고친다.
        return ExecResult(ok=False, http_status=501, error_kind="not_implemented",
                          detail="파이1 팔 API 미구현 (/arm/pose = 501)")


class MockPi1:
    def __init__(self, fail: Optional[dict[str, int]] = None):
        self.fail = dict(fail or {})            # 모션 이름 -> 앞으로 실패할 횟수
        self.act_history: list[str] = []

    def health(self) -> dict:
        return {"camera": {"ok": True}, "arm": {"ok": True}}

    def camera_capture(self) -> bytes:
        return b"\xff\xd8mock-jpeg\xff\xd9"

    def arm_act(self, name: str) -> ExecResult:
        self.act_history.append(name)
        if self.fail.get(name, 0) > 0:
            self.fail[name] -= 1
            return ExecResult(ok=False, http_status=503, error_kind="hw_unavailable",
                              detail=f"mock failure: {name}")
        return ExecResult(ok=True, http_status=200, duration_s=0.01)


# ================================================================ Toolbox

class Toolbox:
    """Action 하나를 알맞은 파이로 보내고, 관측값을 한 번에 모은다.

    - 한 번에 하나의 호출만 실행한다 (락). 병렬 실행은 하지 않는다.
    - 팔 안전 자세 검사 같은 '파이 간' 안전 규칙은 여기가 아니라 Executor 에 둔다.
    """

    def __init__(self, pi1, pi2, sleep: Callable[[float], None] = time.sleep):
        self.pi1, self.pi2 = pi1, pi2
        self.allowed_stations: list[str] = []
        self._lock = threading.Lock()
        self._sleep = sleep

    # ---- 시작 전 점검
    def preflight(self) -> list[str]:
        """문제 목록을 돌려준다. 비어 있으면 시작해도 된다."""
        problems: list[str] = []
        for label, client in (("pi2", self.pi2), ("pi1", self.pi1)):
            try:
                h = client.health()
            except ToolError as e:
                problems.append(f"{label} 연결 실패: {e}")
                continue
            for part, info in (h or {}).items():
                if isinstance(info, dict) and info.get("error"):
                    problems.append(f"{label}.{part}: {info['error']}")
            if label == "pi2":
                rail = h.get("rail", {}) if isinstance(h, dict) else {}
                if rail.get("position_known") is False:
                    problems.append("레일 위치를 모름: 사람이 /rail/resume 또는 "
                                    "/rail/set_position 으로 확인해야 한다")
        try:
            self.refresh_stations()
        except ToolError as e:
            problems.append(f"스테이션 목록을 못 읽음: {e}")
        return problems

    def refresh_stations(self) -> list[str]:
        self.allowed_stations = self.pi2.rail_stations()
        return self.allowed_stations

    # ---- 실행
    def execute(self, action: Action) -> ExecResult:
        with self._lock:
            t0 = time.monotonic()
            if action.type == "move_rail":
                if not action.target:
                    return ExecResult(ok=False, error_kind="bad_request",
                                      detail="move_rail 에 target(스테이션 이름)이 없음")
                if self.allowed_stations and action.target not in self.allowed_stations:
                    return ExecResult(ok=False, error_kind="bad_request",
                                      detail=f"허용되지 않은 스테이션: {action.target}")
                return self.pi2.rail_goto(action.target)
            if action.type == "act":
                return self.pi1.arm_act(action.name)
            if action.type == "wait":
                sec = min(float(action.params.get("seconds", 1)), MAX_WAIT_S)
                self._sleep(sec)
                return ExecResult(ok=True, duration_s=time.monotonic() - t0)
            if action.type == "observe":
                return ExecResult(ok=True)      # 실제 읽기는 observe() 가 한다
            return ExecResult(ok=False, error_kind="invalid",
                              detail=f"알 수 없는 type: {action.type}")

    # ---- 관측
    def observe(self, targets: Iterable[str] = ("camera", "sensors", "thermal")) -> Observation:
        targets = set(targets)
        obs = Observation(timestamp=time.time())
        with self._lock:
            if "sensors" in targets:
                try:
                    s = self.pi2.sensors()
                    obs.ph, obs.ec = s.get("ph"), s.get("ec")
                    obs.sensors_stale = bool(s.get("stale", False))
                except ToolError as e:
                    obs.sensors_stale = True    # 못 읽었으면 판단에 쓰지 못하게 한다
                    obs.errors.append(f"sensors: {e}")
            if "thermal" in targets:
                try:
                    t = self.pi2.thermal_rois()
                    obs.thermal_rois = t if isinstance(t, dict) else {"rois": t}
                except ToolError as e:
                    obs.errors.append(f"thermal: {e}")
            if "camera" in targets:
                try:
                    obs.image_jpeg = self.pi1.camera_capture()
                except ToolError as e:
                    obs.errors.append(f"camera: {e}")
        return obs


def make_toolbox(pi1: Optional[str] = None, pi2: Optional[str] = None) -> Toolbox:
    """'mock' 또는 'real'. 지정하지 않으면 환경변수, 그것도 없으면 mock."""
    pi1 = pi1 or os.getenv("AGENT_PI1", "mock")
    pi2 = pi2 or os.getenv("AGENT_PI2", "mock")
    return Toolbox(Pi1Client() if pi1 == "real" else MockPi1(),
                   Pi2Client() if pi2 == "real" else MockPi2())
