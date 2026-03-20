"""
diag.py - 계기판 신호 단독 진단 스크립트

사용법:
  sudo python diag.py speed   # 속도계 0→200 sweep (각 값 2초씩)
  sudo python diag.py rpm     # RPM sweep (각 값 2초씩)
  sudo python diag.py gear    # 기어 P/R/N/D (각 2초씩)
  sudo python diag.py temp    # 수온 200→230 sweep
  sudo python diag.py raw 0x440 00 00 50 04 FF 2A 0B 80  # 원시 바이트 10초
"""

import time
import sys
import signal
import can
from ucan_interface import UCANInterface


def _msg(can_id: int, data: bytes) -> can.Message:
    return can.Message(arbitration_id=can_id, data=data, is_extended_id=False)


def send_loop(ucan: UCANInterface, can_id: int, data: bytes, duration: float):
    """단일 메시지를 10ms 간격으로 duration초 전송"""
    end = time.monotonic() + duration
    counter = 0
    sent = 0
    last_print = time.monotonic()
    while time.monotonic() < end:
        d = bytearray(data)
        if can_id == 0x316:
            d[1] = counter
            d[4] = counter
        ucan.send(_msg(can_id, bytes(d)))
        counter = (counter + 1) & 0xFF
        sent += 1
        now = time.monotonic()
        if now - last_print >= 1.0:
            print(f"    [{sent}프레임 전송중...]", flush=True)
            last_print = now
        time.sleep(0.01)


def test_speed(ucan):
    print("== 속도계 테스트 (각 값 2초씩) ==")
    for kmh in [0, 30, 60, 100, 140, 180, 200, 240, 0]:
        data = bytes([0x00, 0x00, kmh, 0x04, 0xFF, 0x2A, 0x0B, 0x80])
        print(f"  {kmh} km/h → {data.hex(' ')}")
        send_loop(ucan, 0x440, data, duration=2.0)


def test_rpm(ucan):
    print("== RPM 테스트 (각 값 2초씩, byte[3]=RPM/64) ==")
    for rpm in [0, 800, 2000, 3000, 4000, 6000, 8000, 0]:
        raw = min(255, round(rpm / 64))
        data = bytes([0x01, 0x00, 0xFF, raw, 0x00, 0x15, 0x00, 0x70])
        print(f"  {rpm} RPM → byte[3]=0x{raw:02X}({raw}) → {data.hex(' ')}")
        send_loop(ucan, 0x316, data, duration=2.0)


def test_gear(ucan):
    print("== 기어 테스트 (각 2초씩) ==")
    for name, nibble in [("P", 0x0), ("R", 0x7), ("N", 0x6), ("D", 0x5)]:
        gear_byte = 0x40 | nibble
        data = bytes([0x00, gear_byte, 0x40, 0xFF, 0x31, 0x24, 0x0B, 0x00])
        print(f"  {name} → byte[1]=0x{gear_byte:02X} → {data.hex(' ')}")
        send_loop(ucan, 0x43F, data, duration=2.0)


def test_temp(ucan):
    print("== 수온계 테스트 (각 값 1.5초씩) ==")
    for t in [200, 210, 213, 220, 230]:
        data = bytes([0x00, t, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        print(f"  byte[1]={t} → {data.hex(' ')}")
        send_loop(ucan, 0x329, data, duration=1.5)


def test_all(ucan):
    """모든 게이지 동시 전송: 수온/연료 절반, RPM/속도 최대 (10초)"""
    print("== ALL 테스트: RPM 최대 + 속도 최대 + 수온 절반 (10초) ==")

    # 0x316 byte[3]: RPM/64 → 8000RPM = 125
    # 0x440 byte[2]: km/h → 240
    # 0x329 byte[1]: 수온 절반 = (200+230)/2 = 215
    # 0x43F: 기어 D
    msgs = {
        0x18F: bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x40]),  # IG ON
        0x440: bytes([0x00, 0x00, 240,  0x04, 0xFF, 0x2A, 0x0B, 0x80]),  # 240 km/h
        0x280: bytes([0x21, 0x0D, 240,  0x95, 0x19, 0x1B, 0x4B, 0x2E]),  # 240 km/h
        0x316: bytes([0x01, 0x00, 0xFF, 125,  0x00, 0x15, 0x00, 0x70]),  # 8000 RPM
        0x43F: bytes([0x00, 0x45, 0x40, 0xFF, 0x31, 0x24, 0x0B, 0x00]),  # 기어 D
        0x329: bytes([0x00, 215,  0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),  # 수온 절반
        0x1F1: bytes(8),                                                   # 경고등 off
    }
    print(f"  RPM=8000 (byte[3]=125), Speed=240, Temp=215")

    end = time.monotonic() + 1.0
    counter = 0
    sent = 0
    last_print = time.monotonic()
    while time.monotonic() < end:
        for can_id, data in msgs.items():
            d = bytearray(data)
            if can_id == 0x316:
                d[1] = counter
                d[4] = counter
            ucan.send(_msg(can_id, bytes(d)))
        counter = (counter + 1) & 0xFF
        sent += 1
        now = time.monotonic()
        if now - last_print >= 1.0:
            print(f"    [{sent}사이클 전송중...]", flush=True)
            last_print = now
        time.sleep(0.01)


def test_raw(ucan):
    if len(sys.argv) < 10:
        print("사용법: sudo python diag.py raw 0x440 00 00 50 04 FF 2A 0B 80")
        return
    can_id = int(sys.argv[2], 16)
    data = bytes(int(b, 16) for b in sys.argv[3:11])
    print(f"전송: ID=0x{can_id:03X}  data={data.hex(' ')}  (10초)")
    send_loop(ucan, can_id, data, duration=10.0)


TESTS = {
    "speed": test_speed,
    "rpm":   test_rpm,
    "gear":  test_gear,
    "temp":  test_temp,
    "all":   test_all,
    "raw":   test_raw,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in TESTS:
        print("사용법: sudo python diag.py [speed|rpm|gear|temp|all|raw]")
        sys.exit(1)

    ucan = UCANInterface()
    print("UCAN 연결 중...")
    try:
        ucan.connect()
    except Exception as e:
        print(f"연결 실패: {e}")
        sys.exit(1)
    print("연결 성공!\n")

    def _sig(_s, _f):
        print("\n중단됨")
        ucan.close()
        sys.exit(0)
    signal.signal(signal.SIGINT, _sig)

    try:
        TESTS[sys.argv[1]](ucan)
    finally:
        ucan.close()


if __name__ == "__main__":
    main()
