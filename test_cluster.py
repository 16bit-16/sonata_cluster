"""
test_cluster.py
ETS2 연결 없이 계기판 동작을 직접 테스트하는 스크립트.

사용법:
  python test_cluster.py              # 전체 시연 시퀀스
  python test_cluster.py --port COM3  # 포트 직접 지정
  python test_cluster.py --demo idle  # 특정 시나리오만
"""

import argparse
import time
import signal
import sys
import logging
from ucan_interface import UCANInterface
from can_converter import msg_speed, msg_rpm, msg_gear, msg_coolant, msg_brake, msg_start

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

SEND_HZ = 20
INTERVAL = 1.0 / SEND_HZ


# ── 헬퍼 ────────────────────────────────────────────────────────────────────

def send_state(ucan: UCANInterface, speed: float, rpm: float,
               gear: str, temp: float, duration: float):
    """지정한 값을 duration(초) 동안 20Hz로 전송."""
    msgs = [
        msg_start(),
        msg_speed(speed),
        msg_rpm(rpm),
        msg_gear(gear),
        msg_coolant(temp),
        msg_brake(),
    ]
    end = time.monotonic() + duration
    while time.monotonic() < end:
        t0 = time.monotonic()
        ucan.send_all(msgs)
        elapsed = time.monotonic() - t0
        if INTERVAL - elapsed > 0:
            time.sleep(INTERVAL - elapsed)


def send_sweep(ucan: UCANInterface,
               speed_range: tuple[float, float],
               rpm_range: tuple[float, float],
               gear: str, temp: float, duration: float):
    """속도/RPM을 duration(초) 동안 선형으로 변화시키며 전송."""
    end = time.monotonic() + duration
    start = time.monotonic()
    while True:
        now = time.monotonic()
        if now >= end:
            break
        ratio = (now - start) / duration
        speed = speed_range[0] + (speed_range[1] - speed_range[0]) * ratio
        rpm   = rpm_range[0]   + (rpm_range[1]   - rpm_range[0])   * ratio
        msgs = [
            msg_start(),
            msg_speed(speed),
            msg_rpm(rpm),
            msg_gear(gear),
            msg_coolant(temp),
            msg_brake(),
        ]
        t0 = time.monotonic()
        ucan.send_all(msgs)
        elapsed = time.monotonic() - t0
        if INTERVAL - elapsed > 0:
            time.sleep(INTERVAL - elapsed)

        print(f"\r  speed={speed:5.1f} km/h  rpm={rpm:5.0f}  gear={gear}  temp={temp:.0f}°C",
              end="", flush=True)
    print()


# ── 시나리오 ─────────────────────────────────────────────────────────────────

def demo_idle(ucan: UCANInterface):
    """공회전 상태 - 모든 바늘이 0/중립."""
    log.info("▶ 공회전 (3초)")
    send_state(ucan, speed=0, rpm=800, gear="N", temp=213, duration=3.0)


def demo_warmup(ucan: UCANInterface):
    """엔진 워밍업 - 수온 상승."""
    log.info("▶ 워밍업: 수온 상승 (cold → normal, 3초)")
    end = time.monotonic() + 3.0
    start = time.monotonic()
    while time.monotonic() < end:
        ratio = (time.monotonic() - start) / 3.0
        temp = 40 + ratio * (90 - 40)  # 40°C → 90°C
        msgs = [msg_start(), msg_speed(0), msg_rpm(800),
                msg_gear("N"), msg_coolant(temp), msg_brake()]
        t0 = time.monotonic()
        ucan.send_all(msgs)
        elapsed = time.monotonic() - t0
        if INTERVAL - elapsed > 0:
            time.sleep(INTERVAL - elapsed)
        print(f"\r  temp={temp:.1f}°C", end="", flush=True)
    print()


def demo_drive(ucan: UCANInterface):
    """주행 시퀀스 - 가속/순항/감속."""
    log.info("▶ P → R → N → D 기어 전환 (각 1초)")
    for g in ["P", "R", "N", "D"]:
        log.info(f"   기어: {g}")
        send_state(ucan, speed=0, rpm=800, gear=g, temp=213, duration=1.0)

    log.info("▶ 가속: 0 → 120 km/h (4초)")
    send_sweep(ucan, (0, 120), (800, 4000), "D", 213, duration=4.0)

    log.info("▶ 순항: 120 km/h (2초)")
    send_state(ucan, speed=120, rpm=3000, gear="D", temp=213, duration=2.0)

    log.info("▶ 감속: 120 → 0 km/h (3초)")
    send_sweep(ucan, (120, 0), (3000, 800), "D", 213, duration=3.0)


def demo_warning(ucan: UCANInterface):
    """경고등 테스트 - ABS / BRK."""
    log.info("▶ ABS 경고등 ON (1.5초)")
    end = time.monotonic() + 1.5
    while time.monotonic() < end:
        ucan.send_all([msg_start(), msg_speed(0), msg_rpm(800),
                       msg_gear("P"), msg_coolant(213), msg_brake(abs_warn=True)])
        time.sleep(INTERVAL)

    log.info("▶ 브레이크 경고등 ON (1.5초)")
    end = time.monotonic() + 1.5
    while time.monotonic() < end:
        ucan.send_all([msg_start(), msg_speed(0), msg_rpm(800),
                       msg_gear("P"), msg_coolant(213), msg_brake(brk_warn=True)])
        time.sleep(INTERVAL)

    log.info("▶ 경고등 모두 OFF (1초)")
    send_state(ucan, speed=0, rpm=800, gear="P", temp=213, duration=1.0)


def demo_all(ucan: UCANInterface):
    demo_idle(ucan)
    demo_warmup(ucan)
    demo_drive(ucan)
    demo_warning(ucan)
    log.info("✓ 전체 시연 완료")


# ── 진입점 ───────────────────────────────────────────────────────────────────

DEMOS = {
    "idle":    demo_idle,
    "warmup":  demo_warmup,
    "drive":   demo_drive,
    "warning": demo_warning,
    "all":     demo_all,
}


def main():
    parser = argparse.ArgumentParser(description="YF Sonata 계기판 테스트")
    parser.add_argument("--channel", default=None, type=int,
                        help="gs_usb 채널 인덱스 (기본: 0)")
    parser.add_argument("--demo", default="all", choices=list(DEMOS.keys()),
                        help="실행할 시나리오 (기본: all)")
    args = parser.parse_args()

    ucan = UCANInterface()
    try:
        ucan.connect(channel=args.channel)
    except Exception as e:
        log.error(f"UCAN 연결 실패: {e}")
        sys.exit(1)

    # Ctrl+C 처리
    interrupted = False
    def _sig(_s, _f):
        nonlocal interrupted
        interrupted = True
    signal.signal(signal.SIGINT, _sig)

    try:
        DEMOS[args.demo](ucan)
    except Exception as e:
        log.exception(f"테스트 중 오류: {e}")
    finally:
        if interrupted:
            log.info("중단됨 - 바늘 归零 중...")
        # 바늘을 0으로 복귀
        send_state(ucan, speed=0, rpm=0, gear="P", temp=213, duration=0.5)
        ucan.close()


if __name__ == "__main__":
    main()
