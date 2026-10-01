"""에이전트 설정. 팀과 합의해서 바뀔 값은 전부 여기에 모은다.

⚠ AVAILABLE_ACTIONS 의 이름과 ends_safe 는 '임시'다.
   ACT 로 학습시킬 모션 목록이 정해지면 이 파일만 고친다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Motion:
    description: str
    # 이 모션이 끝났을 때 팔이 '레일을 움직여도 되는 자세'인가.
    # 파이1/파이2 는 서로의 상태를 모르므로, 에이전트가 이 값으로 충돌을 막는다.
    ends_safe: bool


AVAILABLE_ACTIONS: dict[str, Motion] = {
    "grasp_reagent": Motion("시약병 잡기 (운반 자세로 끝남)", ends_safe=True),
    "pour_reagent": Motion("시약 붓기 (팔이 뻗은 채로 끝남)", ends_safe=False),
    "stir": Motion("교반 (팔이 뻗은 채로 끝남)", ends_safe=False),
    "stow_arm": Motion("팔을 안전 자세로 접기", ends_safe=True),
}

SAFE_POSE_MOTION = "stow_arm"      # 인터락에 걸렸을 때 끼워 넣는 복구 모션

OBSERVE_TARGETS = ("camera", "sensors", "thermal")

# 고정 계획(FixedPlanner)이 쓰는 스테이션. 실제 이름은 GET /rail/stations 로 확인.
STATION_REAGENT = "시약존"
STATION_WORK = "비커존"

# 루프 한계
MAX_RETRIES = 2        # 같은 액션 재시도 횟수
MAX_REPLANS = 3        # 한 번의 실행에서 재계획 횟수
MAX_STEPS = 60         # 총 실행 스텝 (무한 루프 방지)
RETRY_WAIT_S = 1.0
