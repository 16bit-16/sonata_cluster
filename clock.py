"""
clock.py - 계기판 시계

속도계 → 시 (hour × 10 km/h, 14시 = 140km/h)
타코미터 → 분 (minute × 100 RPM, 35분 = 3500 RPM = 타코 3.5)
수온계 → 초 (0초=200, 10초=205, 20초=210 ... 60초=230, 1/6씩 이동)

사용법: sudo python clock.py
"""

import time
import signal
import datetime
import can
from ucan_interface import UCANInterface

running = True
def _sig(s, f): global running; running = False
signal.signal(signal.SIGINT, _sig)
signal.signal(signal.SIGTERM, _sig)

def _msg(can_id, data):
    return can.Message(arbitration_id=can_id, data=data, is_extended_id=False)

def clock_msgs(h: int, m: int, s: int) -> list:
    # 속도: 시 × 10 km/h
    speed = h * 10

    # RPM: 분 × 100 RPM (타코 needle: 분/10 위치)
    # byte[3] = RPM / 64
    rpm_raw = round(m * 100 / 64)

    # 수온: 초에 따라 200~230 선형 (매 10초마다 1/6씩)
    # 200 + (s/60)*30 = 200 + s*0.5
    temp = round(200 + s * 30 / 60)

    speed_data  = bytes([0x00, 0x00, speed,   0x04, 0xFF, 0x2A, 0x0B, 0x80])
    speed2_data = bytes([0x21, 0x0D, speed,   0x95, 0x19, 0x1B, 0x4B, 0x2E])
    gear_data   = bytes([0x00, 0x45, 0x40,    0xFF, 0x31, 0x24, 0x0B, 0x00])
    ignit_data  = bytes([0x00, 0x00, 0x00,    0x00, 0x00, 0x00, 0x00, 0x40])
    warn_data   = bytes(8)

    return [
        (0x18F, ignit_data),
        (0x440, speed_data),
        (0x280, speed2_data),
        (0x43F, gear_data),
        (0x1F1, warn_data),
        # RPM과 수온은 아래에서 counter와 함께 처리
        ("rpm",  rpm_raw),
        ("temp", temp),
    ]

def main():
    ucan = UCANInterface()

    while running:
        try:
            print("UCAN 연결 중...")
            ucan.connect()
            break
        except Exception as e:
            print(f"연결 실패: {e} - 3초 후 재시도...")
            time.sleep(3)

    print("시계 시작. 종료: Ctrl+C\n")
    print("  속도계 = 시(hour×10)  |  타코 = 분(min×100RPM)  |  수온 = 초(0→230)")
    print()

    counter = 0
    interval = 0.01  # 100Hz

    while running:
        t0 = time.monotonic()
        now = datetime.datetime.now()
        h, m, s = now.hour, now.minute, now.second

        # 로그 (1초마다)
        if counter % 100 == 0:
            temp_val = round(200 + s * 30 / 60)
            rpm_raw  = round(m * 100 / 64)
            print(f"\r  {h:02d}:{m:02d}:{s:02d}  "
                  f"speed={h*10}km/h  rpm={m*100}({rpm_raw})  temp={temp_val}  ",
                  end="", flush=True)

        speed = h * 10
        rpm_raw = round(m * 100 / 64)
        temp = round(200 + s * 30 / 60)

        msgs = [
            _msg(0x440, bytes([counter & 0xFF, 0x00, speed, 0x04, 0xFF, 0x2A, 0x0B, 0x80])),
            _msg(0x43F, bytes([0x00, 0x45, 0x40, 0xFF, 0x31, 0x24, 0x0B, 0x00])),
            _msg(0x316, bytes([0x01, counter & 0xFF, 0xFF, rpm_raw,
                               counter & 0xFF, 0x15, 0x00, 0x70])),
            _msg(0x329, bytes([0x00, temp, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])),
            _msg(0x1F1, bytes(8)),
        ]

        for msg in msgs:
            ucan.send(msg)

        counter = (counter + 1) & 0xFF

        elapsed = time.monotonic() - t0
        sleep = interval - elapsed
        if sleep > 0:
            time.sleep(sleep)

    print("\n종료")
    ucan.close()

if __name__ == "__main__":
    main()
