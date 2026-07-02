"""워커 자막 fetch 글로벌 페이싱 단위 테스트 (0단계 F2 밴 예방).

네트워크 없이 Pacer 의 동시성 상한 + 시작 간격 + 지터 상한만 검증.
결정적 테스트를 위해 monotonic/sleep/rand 를 주입한다.
"""
from __future__ import annotations

import threading

import pacing as pc


class _FakeClock:
    """주입용 가짜 시계 — sleep 하면 그만큼 t 가 흐른 것으로 친다(결정적)."""

    def __init__(self) -> None:
        self.t = 0.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.t

    def sleep(self, d: float) -> None:
        self.slept.append(d)
        self.t += d


def test_spacing_enforces_min_interval():
    clock = _FakeClock()
    p = pc.Pacer(max_inflight=4, min_interval_s=2.0, jitter_s=0.0,
                 monotonic=clock.monotonic, sleep=clock.sleep, rand=lambda: 0.0)
    with p.slot():
        pass
    with p.slot():
        pass
    with p.slot():
        pass
    # 첫 slot 은 대기 없음, 이후는 min_interval(2.0) 만큼 간격 확보.
    assert clock.slept == [2.0, 2.0]


def test_jitter_bounded_by_min_plus_jitter():
    clock = _FakeClock()
    p = pc.Pacer(max_inflight=4, min_interval_s=1.0, jitter_s=1.0,
                 monotonic=clock.monotonic, sleep=clock.sleep, rand=lambda: 1.0)
    with p.slot():
        pass
    with p.slot():
        pass
    # rand=1.0 → 간격 = min(1.0) + jitter(1.0) = 2.0. 절대 min+jitter 초과 안 함.
    assert clock.slept == [2.0]
    assert clock.slept[0] <= 1.0 + 1.0


def test_max_inflight_blocks_extra_slot():
    # 실제 스레드로 동시성 상한 검증. 간격 0 으로 두어 spacing 간섭 제거.
    p = pc.Pacer(max_inflight=1, min_interval_s=0.0, jitter_s=0.0)
    entered = threading.Event()
    release = threading.Event()
    second_entered = threading.Event()

    def hold():
        with p.slot():
            entered.set()
            release.wait(2.0)

    def second():
        with p.slot():
            second_entered.set()

    t1 = threading.Thread(target=hold)
    t1.start()
    assert entered.wait(1.0)                    # 첫 slot 진입

    t2 = threading.Thread(target=second)
    t2.start()
    assert not second_entered.wait(0.3)        # 상한=1 이라 두 번째는 대기

    release.set()                               # 첫 slot 해제
    assert second_entered.wait(1.0)            # 이제 두 번째 진입
    t1.join(1.0)
    t2.join(1.0)
