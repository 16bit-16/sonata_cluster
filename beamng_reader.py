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
OG_HANDBRAKE = 0x2000


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
        (time_, car, flags, gear, plid,
         speed, rpm, turbo, eng_temp, fuel, oil_p, oil_t,
         dash_lights, show_lights,
         throttle, brake, clutch,
         display1, display2, id_) = struct.unpack(OG_FMT, raw)

        d = self._data
        d.speed_ms      = speed        # m/s
        d.rpm           = rpm
        d.coolant_temp  = eng_temp     # celsius
        d.fuel          = fuel         # 0.0~1.0 (ratio)
        d.fuel_capacity = 1.0
        d.engine_on     = rpm > 100
        d.parking_brake = bool(show_lights & OG_HANDBRAKE)

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
