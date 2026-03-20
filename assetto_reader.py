"""
assetto_reader.py - Assetto Corsa shared memory reader (Windows 전용)

AC가 실행 중이면 자동으로 공유메모리 생성됨. 별도 플러그인 불필요.
"""

import mmap
import struct
import sys
import logging
from telemetry_reader import TelemetryData

log = logging.getLogger(__name__)

# acpmf_physics 첫 부분 (필요한 필드만 파싱)
# int packetId, float gas, brake, fuel, gear, rpms, steerAngle, speedKmh
AC_PHYSICS_FMT  = '<i7f'
AC_PHYSICS_SIZE = 4096

# acpmf_graphics 첫 부분
# int packetId, int status, int session, ...
AC_GRAPHICS_FMT  = '<iii'
AC_GRAPHICS_SIZE = 4096


class AssettoCorsaReader:
    def __init__(self):
        self._physics: mmap.mmap | None = None
        self._data = TelemetryData()

    def connect(self):
        if sys.platform != "win32":
            raise RuntimeError("Assetto Corsa shared memory는 Windows 전용입니다")
        self._physics = mmap.mmap(
            -1, AC_PHYSICS_SIZE,
            tagname="Local\\acpmf_physics",
            access=mmap.ACCESS_READ,
        )
        log.info("Assetto Corsa shared memory 연결됨")

    def read(self) -> TelemetryData:
        if not self._physics:
            return self._data
        try:
            self._physics.seek(0)
            raw = self._physics.read(struct.calcsize(AC_PHYSICS_FMT))
            packet_id, gas, brake, fuel, gear, rpms, steer, speed_kmh = \
                struct.unpack(AC_PHYSICS_FMT, raw)

            d = self._data
            d.speed_ms     = speed_kmh / 3.6
            d.rpm          = rpms
            d.fuel         = fuel          # 0.0~1.0
            d.fuel_capacity = 1.0
            d.engine_on    = rpms > 100
            d.coolant_temp = 90.0          # AC 공유메모리에 수온 없음

            # Gear: 0=R, 1=N, 2=1st, 3=2nd ...
            if gear == 0:
                d.gear = -1
            elif gear == 1:
                d.gear = 0
            else:
                d.gear = gear - 1

        except Exception as e:
            log.warning(f"AC 읽기 오류: {e}")
        return self._data

    def close(self):
        if self._physics:
            self._physics.close()
            self._physics = None
