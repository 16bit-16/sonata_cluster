"""
ucan_direct.py - pyusb로 gs_usb 프로토콜 직접 구현 (python-can 우회)
C 테스트(can_test.c)와 동일한 방식. HW_TIMESTAMP 없이 20바이트 프레임 사용.

사용법: sudo python ucan_direct.py
"""

import struct
import time
import usb.core
import usb.util
import signal
import sys

# gs_usb control request codes
GSUSB_BREQ_HOST_FORMAT = 0
GSUSB_BREQ_BITTIMING   = 1
GSUSB_BREQ_MODE        = 2

GS_CAN_MODE_RESET = 0
GS_CAN_MODE_START = 1

VID, PID = 0x1D50, 0x606F
EP_OUT, EP_IN = 0x02, 0x81

# 500kbps @ 48MHz: prop=2, ps1=11, ps2=2, sjw=1, brp=6 → 16TQ = 500kbps
# struct: prop_seg, phase_seg1, phase_seg2, sjw, brp (all uint32 LE)
BITTIMING_500K = struct.pack("<IIIII", 2, 11, 2, 1, 6)

running = True
def _sig(s, f): global running; running = False
signal.signal(signal.SIGINT, _sig)


def pack_frame(echo_id: int, can_id: int, dlc: int, data: bytes) -> bytes:
    """gs_frame_t: echo_id, can_id, dlc, channel, flags, pad, data[8] = 20 bytes"""
    d = (data + b'\x00' * 8)[:8]
    return struct.pack("<II", echo_id, can_id) + bytes([dlc, 0, 0, 0]) + d


def send_ctrl(dev, breq: int, data: bytes):
    dev.ctrl_transfer(
        bmRequestType=0x41,  # VENDOR | INTERFACE | OUT
        bRequest=breq,
        wValue=0, wIndex=0,
        data_or_wLength=data,
        timeout=1000,
    )


def setup_device():
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        raise RuntimeError(f"UCAN 장치 없음 (sudo 필요?)")

    # 커널 드라이버 분리 (macOS에서는 보통 불필요, 실패해도 무시)
    try:
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
    except Exception:
        pass
    usb.util.claim_interface(dev, 0)

    # host format (little-endian)
    send_ctrl(dev, GSUSB_BREQ_HOST_FORMAT, struct.pack("<I", 0))
    # bittiming 500kbps
    send_ctrl(dev, GSUSB_BREQ_BITTIMING, BITTIMING_500K)
    # 채널 시작 (flags=0: 재전송 허용, HW_TIMESTAMP 없음)
    send_ctrl(dev, GSUSB_BREQ_MODE, struct.pack("<II", GS_CAN_MODE_START, 0))

    print(f"UCAN 연결 완료 ({VID:04X}:{PID:04X}), 500kbps")
    return dev


def stop_device(dev):
    try:
        send_ctrl(dev, GSUSB_BREQ_MODE, struct.pack("<II", GS_CAN_MODE_RESET, 0))
        usb.util.release_interface(dev, 0)
    except Exception:
        pass


def send_frame(dev, can_id: int, data: bytes, echo_id: int = 0):
    frame = pack_frame(echo_id, can_id, len(data), data)
    dev.write(EP_OUT, frame, timeout=200)


def recv_frame(dev, timeout_ms: int = 1):
    """에러 프레임 포함 수신. None 반환이면 타임아웃."""
    try:
        raw = dev.read(EP_IN, 20, timeout=timeout_ms)
        if len(raw) >= 20:
            echo_id, can_id = struct.unpack_from("<II", raw, 0)
            dlc = raw[4]
            data = bytes(raw[8:16])
            return can_id, dlc, data
    except usb.core.USBTimeoutError:
        pass
    except usb.core.USBError:
        pass
    return None


class DirectBus:
    """python-can 없이 직접 UCAN 제어"""

    def __init__(self):
        self._dev = setup_device()
        self._echo = 0
        self._counter = 0

    def send(self, can_id: int, data: bytes):
        d = bytearray(data)
        if can_id == 0x316:
            d[1] = self._counter
            d[4] = self._counter
        send_frame(self._dev, can_id, bytes(d), self._echo)
        self._echo = (self._echo + 1) & 0xFFFFFFFF
        self._counter = (self._counter + 1) & 0xFF

    def close(self):
        stop_device(self._dev)


# ── 메시지 데이터 ────────────────────────────────────────────────────────────

def rpm_data(rpm: int) -> bytes:
    raw = min(255, round(rpm / 64))
    return bytes([0x01, 0x00, 0xFF, raw, 0x00, 0x15, 0x00, 0x70])

BASELINE = {
    0x18F: bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x40]),
    0x440: bytes([0x00, 0x00, 0x00, 0x04, 0xFF, 0x2A, 0x0B, 0x80]),
    0x43F: bytes([0x00, 0x45, 0x40, 0xFF, 0x31, 0x24, 0x0B, 0x00]),
    0x316: rpm_data(800),
    0x329: bytes([0x00, 0xD5, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
    0x1F1: bytes(8),
}


def test_rpm(bus: DirectBus):
    """RPM sweep: 각 값 3초씩"""
    print("== RPM sweep (byte[3]=RPM/64) ==")
    for rpm in [800, 2000, 3000, 4000, 1000]:
        data = rpm_data(rpm)
        raw = data[3]
        print(f"  {rpm} RPM → byte[3]={raw} (0x{raw:02X})")
        end = time.monotonic() + 3.0
        sent = 0
        while time.monotonic() < end and running:
            bus.send(0x316, data)
            sent += 1
            # 에러 프레임 소비 (블로킹 없이)
            recv_frame(bus._dev, timeout_ms=1)
            time.sleep(0.01)
        print(f"    {sent}프레임 전송")


def main():
    print("UCAN 직접 연결 중 (python-can 우회)...")
    try:
        bus = DirectBus()
    except Exception as e:
        print(f"연결 실패: {e}")
        sys.exit(1)

    try:
        test_rpm(bus)
    finally:
        bus.close()
        print("종료")


if __name__ == "__main__":
    main()
