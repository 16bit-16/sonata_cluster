"""
ucan_interface.py
FYSETC UCAN (CandleLight 펌웨어) pyusb 직접 제어.

python-can gs_usb는 GS_CAN_MODE_HW_TIMESTAMP 플래그로 24바이트 프레임을 전송해
클러스터가 오동작함. pyusb 직접 구현으로 flags=0 (20바이트) 사용.

의존성: pip install pyusb
실행:   sudo python main.py
"""

import sys
import struct
import logging
import can
import usb.core
import usb.util
import usb.backend.libusb1

def _get_backend():
    if sys.platform == "win32":
        try:
            import libusb_package
            return usb.backend.libusb1.get_backend(find_library=libusb_package.find_library)
        except Exception:
            pass
    return usb.backend.libusb1.get_backend()

log = logging.getLogger(__name__)

_BREQ_HOST_FORMAT = 0
_BREQ_BITTIMING   = 1
_BREQ_MODE        = 2

_MODE_RESET = 0
_MODE_START = 1

_VID, _PID   = 0x1D50, 0x606F
_EP_OUT      = 0x02
_EP_IN       = 0x81

# 500kbps @ 48MHz: prop=2, ps1=11, ps2=2, sjw=1, brp=6 → 16TQ, 87.5% SP
_BITTIMING_500K = struct.pack("<IIIII", 2, 11, 2, 1, 6)


def _ctrl(dev, breq: int, data: bytes):
    dev.ctrl_transfer(0x41, breq, 0, 0, data, timeout=1000)


def _pack_frame(echo_id: int, can_id: int, dlc: int, data: bytes) -> bytes:
    """gs_frame_t 20 bytes: echo_id(4)+can_id(4)+dlc/ch/flags/pad(4)+data(8)"""
    d = (data + b'\x00' * 8)[:8]
    return struct.pack("<II", echo_id, can_id) + bytes([dlc, 0, 0, 0]) + d


class UCANInterface:
    def __init__(self):
        self._dev  = None
        self._echo = 0
        self._send_count = 0

    def connect(self):
        dev = usb.core.find(idVendor=_VID, idProduct=_PID, backend=_get_backend())
        if dev is None:
            raise RuntimeError("UCAN 장치를 찾을 수 없습니다 (sudo 필요?)")

        try:
            if dev.is_kernel_driver_active(0):
                dev.detach_kernel_driver(0)
        except Exception:
            pass
        usb.util.claim_interface(dev, 0)

        # 클린 시작: 기존 모드 리셋 후 재설정
        try:
            _ctrl(dev, _BREQ_MODE, struct.pack("<II", _MODE_RESET, 0))
        except Exception:
            pass

        _ctrl(dev, _BREQ_HOST_FORMAT, struct.pack("<I", 0))
        _ctrl(dev, _BREQ_BITTIMING, _BITTIMING_500K)
        _ctrl(dev, _BREQ_MODE, struct.pack("<II", _MODE_START, 0))

        self._dev = dev
        self._echo = 0
        self._send_count = 0
        log.info(f"UCAN 연결 ({_VID:04X}:{_PID:04X}) 500kbps flags=0")

    def _drain(self):
        """IN 버퍼의 에러 프레임 소비 (1ms 타임아웃)."""
        try:
            self._dev.read(_EP_IN, 24, timeout=1)
        except Exception:
            pass

    def send(self, msg: can.Message):
        if self._dev is None:
            log.warning("UCAN 미연결")
            return
        can_id = msg.arbitration_id
        if msg.is_extended_id:
            can_id |= 0x80000000
        frame = _pack_frame(self._echo, can_id, msg.dlc, bytes(msg.data))
        try:
            self._dev.write(_EP_OUT, frame, timeout=200)
            self._echo = (self._echo + 1) & 0xFFFFFFFF
            self._send_count += 1
            # 매 프레임마다 IN 버퍼 드레인 (에러 프레임 누적 방지)
            self._drain()
        except usb.core.USBError as e:
            log.error(f"CAN 전송 오류: {e}")

    def send_all(self, messages: list[can.Message]):
        for msg in messages:
            self.send(msg)

    def close(self):
        if self._dev:
            try:
                _ctrl(self._dev, _BREQ_MODE, struct.pack("<II", _MODE_RESET, 0))
                usb.util.release_interface(self._dev, 0)
            except Exception:
                pass
            self._dev = None
            log.info("UCAN 연결 해제")
