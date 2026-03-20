"""
telemetry_reader.py
ETS2 SCS SDK 플러그인으로부터 텔레메트리 데이터를 읽어오는 모듈.
Unix Domain Socket 또는 mmap(shared memory) 방식 지원.
"""

import socket
import mmap
import json
import logging
from dataclasses import dataclass
from typing import Optional
from config import SOCKET_PATH, IPC_MODE

log = logging.getLogger(__name__)


@dataclass
class TelemetryData:
    speed_ms: float = 0.0        # 속도 (m/s)
    rpm: float = 0.0             # 엔진 RPM
    fuel: float = 0.0            # 연료량 (리터)
    fuel_capacity: float = 1.0   # 연료 탱크 용량 (리터)
    gear: int = 0                # 현재 기어 (음수=후진, 0=중립)
    engine_on: bool = False      # 엔진 켜짐 여부
    parking_brake: bool = False  # 주차 브레이크
    blinker_left: bool = False
    blinker_right: bool = False
    oil_pressure: float = 0.0   # 오일 압력 (kPa)
    coolant_temp: float = 20.0  # 냉각수 온도 (°C)
    odometer: float = 0.0       # 주행 거리 (km)

    @property
    def speed_kmh(self) -> float:
        return self.speed_ms * 3.6

    @property
    def fuel_ratio(self) -> float:
        if self.fuel_capacity <= 0:
            return 0.0
        return max(0.0, min(1.0, self.fuel / self.fuel_capacity))


class TelemetryReader:
    def __init__(self):
        self._data = TelemetryData()
        self._socket: Optional[socket.socket] = None
        self._mmap: Optional[mmap.mmap] = None

    def connect(self):
        if IPC_MODE == "socket":
            self._connect_socket()
        elif IPC_MODE == "mmap":
            self._connect_mmap()
        else:
            raise ValueError(f"Unknown IPC_MODE: {IPC_MODE}")

    def _connect_socket(self):
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket.connect(SOCKET_PATH)
        self._socket.setblocking(False)
        log.info(f"Connected to ETS2 plugin via socket: {SOCKET_PATH}")

    def _connect_mmap(self):
        # TODO: SCS SDK 플러그인이 공유 메모리를 생성한 후 연결
        # import posix_ipc
        # shm = posix_ipc.SharedMemory(SHARED_MEM_NAME)
        # self._mmap = mmap.mmap(shm.fd, shm.size)
        raise NotImplementedError("mmap mode not yet implemented")

    def read(self) -> TelemetryData:
        """최신 텔레메트리 데이터를 반환. 연결 안 된 경우 마지막 값 유지."""
        if IPC_MODE == "socket" and self._socket:
            self._read_socket()
        elif IPC_MODE == "mmap" and self._mmap:
            self._read_mmap()
        return self._data

    def _read_socket(self):
        try:
            raw = self._socket.recv(4096)
            if not raw:
                return
            for line in raw.decode(errors='ignore').replace('}{', '}\n{').splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    self._parse(json.loads(line))
                except json.JSONDecodeError as e:
                    log.warning(f"JSON decode error: {e}")
        except BlockingIOError:
            pass  # 새 데이터 없음

    def _read_mmap(self):
        # TODO: 공유 메모리 파싱 구현
        pass

    def _parse(self, payload: dict):
        d = self._data
        d.speed_ms = payload.get("speed", d.speed_ms)
        d.rpm = payload.get("engineRpm", d.rpm)
        d.fuel = payload.get("fuel", d.fuel)
        d.fuel_capacity = payload.get("fuelCapacity", d.fuel_capacity)
        d.gear = payload.get("gear", d.gear)
        d.engine_on = payload.get("engineEnabled", d.engine_on)
        d.parking_brake = payload.get("parkBrake", d.parking_brake)
        d.blinker_left = payload.get("blinkerLeftActive", d.blinker_left)
        d.blinker_right = payload.get("blinkerRightActive", d.blinker_right)
        d.coolant_temp = payload.get("waterTemperature", d.coolant_temp)
        d.odometer = payload.get("odometer", d.odometer)

    def close(self):
        if self._socket:
            self._socket.close()
            self._socket = None
        if self._mmap:
            self._mmap.close()
            self._mmap = None
