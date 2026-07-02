"""워커 자막 fetch 글로벌 페이싱 — F2(IP/ASN 밴) 예방 (0단계).

왜 워커에서 하나: YouTube 는 요청량보다 IP/ASN 평판으로 차단하지만, 짧은 시간
burst 는 레지덴셜 IP 도 몇 시간 밴시킨다. Azure 는 replica 가 여럿이라 앱쪽 동시성만
낮춰선 부족 — 여러 앱이 같은 워커 1대를 공유하므로 **워커에서 전역으로** 내보내는
자막 fetch 를 제한해야 확실하다.

무엇을: (1) 동시에 진행하는 자막 fetch 수 상한 + (2) 연속 시작 사이 최소 간격 + 지터.
값은 env 가 아니라 코드 상수로 고정한다(운영 튜닝값이라 하드코딩).
"""
from __future__ import annotations

import random
import threading
import time
from contextlib import contextmanager
from typing import Callable, Iterator

# ── 튜닝 상수 (하드코딩) ────────────────────────────────────────────
# 5영상 self-heal 이 60s HTTP 타임아웃 안에 끝나도록 보수적으로 잡았다
# (inflight 2 × 시작간격 ~1.5~2.5s → 5영상 ≈ 7~8s, 10영상 ≈ 15~20s).
MAX_INFLIGHT = 2       # 동시에 진행하는 자막 fetch 수 (burst 제거)
MIN_INTERVAL_S = 1.5   # 연속 fetch 시작 사이 최소 간격(초)
JITTER_S = 1.0         # 위 간격에 더해지는 랜덤 지터(초) — 패턴화 방지


class Pacer:
    """동시성 상한 + 시작 간격 게이트. `with pacer.slot():` 로 감싼다.

    monotonic/sleep/rand 는 테스트 주입용(기본은 실제 구현).
    """

    def __init__(
        self,
        max_inflight: int,
        min_interval_s: float,
        jitter_s: float,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        rand: Callable[[], float] = random.random,
    ) -> None:
        self._sem = threading.Semaphore(max_inflight)
        self._min = min_interval_s
        self._jitter = jitter_s
        self._monotonic = monotonic
        self._sleep = sleep
        self._rand = rand
        self._lock = threading.Lock()
        self._next_allowed = 0.0   # 다음 시작이 허용되는 monotonic 시각

    @contextmanager
    def slot(self) -> Iterator[None]:
        self._sem.acquire()
        try:
            self._wait_turn()
            yield
        finally:
            self._sem.release()

    def _wait_turn(self) -> None:
        # 시작 시각을 직렬화·간격화한다. sleep 을 lock 안에서 하므로 여러 요청이
        # 동시에 몰려도 시작이 min_interval(+jitter) 간격으로 벌어진다.
        with self._lock:
            now = self._monotonic()
            wait = self._next_allowed - now
            if wait > 0:
                self._sleep(wait)
                now += wait
            self._next_allowed = now + self._min + self._jitter * self._rand()


# 워커 전역 단일 인스턴스 — /transcript 라우트가 이걸로 감싼다.
TRANSCRIPT_PACER = Pacer(MAX_INFLIGHT, MIN_INTERVAL_S, JITTER_S)
