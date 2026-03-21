"""
beamng_reader.py - BeamNG.drive outgauge UDP reader

BeamNG 설정: Options → Other → OutGauge → Enable, Port 4444
"""

import socket
import struct
import logging
from telemetry_reader import TelemetryData

log = logging.getLogger(__name__)

# OutGauge protocol (LFS compatible) - 96 bytes
# https://www.lfs.net/programmer/outgauge
OG_FMT  = '<I4sHBB7fII3f16s16si'
OG_SIZE = struct.calcsize(OG_FMT)  # 96 bytes

# DashLights / ShowLights bits
OG_SIGNAL_L  = 0x0004
OG_SIGNAL_R  = 0x0040  # BeamNG: 표준 LFS(0x0008)와 다름
OG_HANDBRAKE = 0x2000
# OG_ABS: BeamNG 매핑 미확인, 비활성화


class BeamNGReader:
    def __init__(self, port: int = 4444):
        self._port = port
        self._sock: socket.socket | None = None
        self._data = TelemetryData()

    def connect(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("0.0.0.0", self._port))
        self._sock.setblocking(False)
        log.info(f"BeamNG outgauge listening on UDP:{self._port}")

    def read(self) -> TelemetryData:
        if not self._sock:
            return self._data
        try:
            raw, _ = self._sock.recvfrom(256)
            if len(raw) >= OG_SIZE:
                self._parse(raw[:OG_SIZE])
        except (BlockingIOError, OSError):
            pass
        return self._data

    def _parse(self, raw: bytes):
        (_, _, _, gear, _,
         speed, rpm, _, eng_temp, fuel, _, _,
         _, show_lights,
         _, _, _,
         _, _, _) = struct.unpack(OG_FMT, raw)

        d = self._data
        d.speed_ms      = speed
        d.rpm           = rpm
        d.coolant_temp  = eng_temp
        d.fuel          = fuel
        d.fuel_capacity = 1.0
        d.engine_on     = rpm > 100
        d.parking_brake  = bool(show_lights & OG_HANDBRAKE)
        d.blinker_left   = bool(show_lights & OG_SIGNAL_L)
        d.blinker_right  = bool(show_lights & OG_SIGNAL_R)

        # Gear: 0=Reverse, 1=Neutral, 2=1st, 3=2nd ...
        if gear == 0:
            d.gear = -1
        elif gear == 1:
            d.gear = 0
        else:
            d.gear = gear - 1

    def close(self):
        if self._sock:
            self._sock.close()
            self._sock = None
