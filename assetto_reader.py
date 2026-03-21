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

# acpmf_physics 오프셋
# 0:packetId(i) 4:gas 8:brake 12:fuel 16:gear(i) 20:rpms 24:steer 28:speedKmh
# 152:tyreCoreTemperature[4]
AC_PHYSICS_SIZE  = 4096
AC_READ_SIZE     = 168   # tyreCoreTemperature 끝까지 (152 + 4×4)


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
            raw = self._physics.read(AC_READ_SIZE)

            # 기본 필드 (offset 0)
            _, _, _, fuel, gear, rpms, _, speed_kmh = \
                struct.unpack_from('<ifffifff', raw, 0)

            # 타이어 코어 온도 평균 → 수온 대용 (offset 152)
            tyre_temps = struct.unpack_from('<4f', raw, 152)
            avg_tyre   = sum(tyre_temps) / 4

            d = self._data
            d.speed_ms      = speed_kmh / 3.6
            d.rpm           = max(0.0, rpms)
            d.fuel          = fuel
            d.fuel_capacity = 1.0
            d.engine_on     = rpms > 100
            d.coolant_temp  = avg_tyre  # 타이어 온도 ≈ 20°C(냉간) ~ 90°C(워밍업)

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
