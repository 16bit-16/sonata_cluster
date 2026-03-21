"""
can_converter.py
TelemetryData -> YF Sonata (94003-3S170) CAN 메시지 변환.

검증된 프로토콜 (AVR 실험 코드 기반, C-CAN 500kbps):
  0x440  속도계     byte[2] = km/h (0~254)
  0x280  속도보조   byte[2] = km/h (0x440과 같은 값, 없으면 속도계 미작동)
  0x316  타코미터   byte[3] = RPM/64  (0x0D≈800rpm, 0x2F≈3000rpm, 0x64=6400rpm)
                   rolling counter: byte[1] = byte[4] (0x00~0xFF 순환)
                   실차 캡처 byte[0]=0x01, byte[5]=0x15, byte[7]=0x70
  0x43F  기어 표시  byte[1] 하위 니블: P=0x?0 R=0x?7 N=0x?6 D=0x?5
  0x329  수온계     byte[1] = 200:cold 213:normal 230:hot
  0x1F1  경고등     byte[0] bit0=ABS bit1=BRK
  0x18F  시동상태   all zeros (IG ON keepalive)
"""

import can
from telemetry_reader import TelemetryData
from config import (
    CAN_ID_SPEED, CAN_ID_SPEED2, CAN_ID_RPM, CAN_ID_GEAR,
    CAN_ID_COOLANT, CAN_ID_BRAKE, CAN_ID_START,
)

# 기어 → byte[1] 하위 니블 변환표
# byte[1] = (상위니블 고정값 0x4) | 하위니블
GEAR_NIBBLE: dict[str, int] = {
    "P": 0, "R": 7, "N": 6, "D": 5,
    "1": 5, "2": 5, "3": 5,  # 수동단은 D로 표시
}

TEMP_FLOOR  = 180  # 바늘 최저 (엔진 냉간)
TEMP_COLD   = 200  # C 마크 (~4/10)
TEMP_NORMAL = 213  # 정상 범위
TEMP_HOT    = 230  # H 마크


def _make(arbitration_id: int, data: bytes) -> can.Message:
    return can.Message(
        arbitration_id=arbitration_id,
        data=data,
        is_extended_id=False,
    )


# ── 개별 메시지 생성 ────────────────────────────────────────────────────────

def msg_speed(kmh: float, counter: int = 0) -> can.Message:
    """0x440: 속도계 byte[2] = km/h, byte[0] = rolling counter"""
    speed = max(0, min(254, int(kmh)))
    data = bytes([counter & 0xFF, 0x00, speed, 0x04, 0xFF, 0x2A, 0x0B, 0x80])
    return _make(CAN_ID_SPEED, data)


def msg_speed2(kmh: float) -> can.Message:
    """0x280: 속도계 보조 메시지 (없으면 속도계 바늘 미작동)"""
    speed = max(0, min(254, int(kmh)))
    data = bytes([0x21, 0x0D, speed, 0x95, 0x19, 0x1B, 0x4B, 0x2E])
    return _make(CAN_ID_SPEED2, data)


def msg_rpm(rpm: float, counter: int = 0) -> can.Message:
    """
    0x316: 타코미터
    byte[3] = RPM / 64  (실측: 50→3200, 75→4800, 100→6400)
    byte[2] = 0xFF (상수)
    byte[1] = byte[4] = rolling counter (0~255)
    """
    raw = max(0, min(255, round(rpm / 64)))
    ctr = counter & 0xFF
    data = bytes([0x01, ctr, 0xFF, raw, ctr, 0x15, 0x00, 0x70])
    return _make(CAN_ID_RPM, data)


def msg_gear(gear: str | int) -> can.Message:
    """
    0x43F: 기어 표시
    byte[1] = 0x4? where ? is: P=0, R=7, N=6, D=5
    """
    if isinstance(gear, str):
        nibble = GEAR_NIBBLE.get(gear.upper(), 6)  # 기본값 N
    else:
        if gear < 0:
            nibble = GEAR_NIBBLE["R"]
        elif gear == 0:
            nibble = GEAR_NIBBLE["N"]
        else:
            nibble = GEAR_NIBBLE["D"]
    gear_byte = 0x40 | nibble
    data = bytes([0x00, gear_byte, 0x40, 0xFF, 0x31, 0x24, 0x0B, 0x00])
    return _make(CAN_ID_GEAR, data)


def msg_coolant(celsius: float) -> can.Message:
    """0x329: 수온계 (byte[1])
    FLOOR(180)=최저  COLD(200)=C마크  NORMAL(213)=정상  HOT(230)=H마크
    """
    if celsius <= 20:
        temp_byte = TEMP_FLOOR
    elif celsius <= 60:
        ratio = (celsius - 20) / (60 - 20)
        temp_byte = int(TEMP_FLOOR + ratio * (TEMP_COLD - TEMP_FLOOR))
    elif celsius >= 110:
        temp_byte = TEMP_HOT
    else:
        ratio = (celsius - 60) / (110 - 60)
        temp_byte = int(TEMP_COLD + ratio * (TEMP_HOT - TEMP_COLD))
    data = bytes([0x00, temp_byte, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
    return _make(CAN_ID_COOLANT, data)


def msg_brake(abs_warn: bool = False, brk_warn: bool = False) -> can.Message:
    """0x1F1: ABS/브레이크 경고등"""
    state = (0x01 if abs_warn else 0) | (0x02 if brk_warn else 0)
    data = bytes([state, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
    return _make(CAN_ID_BRAKE, data)


def msg_start() -> can.Message:
    """0x18F: IG ON keepalive (byte[7]=0x40: 시동완료 출발메시지)"""
    return _make(CAN_ID_START, bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x40]))


# ── 텔레메트리 → 전체 메시지 목록 ──────────────────────────────────────────

class CANConverter:
    def __init__(self):
        self._counter = 0

    def convert(self, d: TelemetryData) -> list[can.Message]:
        msgs = [
            msg_start(),
            msg_speed(d.speed_kmh, self._counter),
            msg_rpm(d.rpm, self._counter),
            msg_gear(d.gear),
            msg_coolant(d.coolant_temp),
            msg_brake(abs_warn=d.abs_active, brk_warn=d.parking_brake),
        ]
        self._counter = (self._counter + 1) & 0xFF
        return msgs
