"""
find_fuel.py - 연료계 CAN ID 자동 탐색

게이지가 움직이면 아무 키나 누르세요.
사용법: sudo python find_fuel.py
"""

import time, sys, signal, termios, tty, select, threading
import can
from ucan_interface import UCANInterface

running = True
def _sig(s, f): global running; running = False
signal.signal(signal.SIGINT, _sig)

def _msg(can_id, data):
    return can.Message(arbitration_id=can_id, data=data, is_extended_id=False)

# 이미 알고 있는 ID 제외
KNOWN = {0x18F, 0x1F1, 0x280, 0x316, 0x329, 0x43F, 0x440, 0x4F0, 0x690}

# ── 키 감지 (non-blocking) ─────────────────────────────────────────────────
_key_pressed = threading.Event()

def _key_reader():
    global running
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while running:
            if select.select([sys.stdin], [], [], 0.1)[0]:
                ch = sys.stdin.read(1)
                if ch == '\x03':   # Ctrl+C
                    running = False
                    break
                _key_pressed.set()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

threading.Thread(target=_key_reader, daemon=True).start()

# ── 전송 헬퍼 ──────────────────────────────────────────────────────────────
def send_for(ucan, can_id, data, duration):
    end = time.monotonic() + duration
    while time.monotonic() < end and running:
        ucan.send(_msg(can_id, data))
        time.sleep(0.01)

# ── 단계 1: 빠른 전체 스캔 ─────────────────────────────────────────────────
def fast_scan(ucan):
    """각 ID에 0xFF*8을 0.5초 전송 → 움직임 감지 시 해당 ID 반환"""
    candidates = [i for r in [range(0x300,0x500), range(0x100,0x300), range(0x500,0x780)]
                  for i in r if i not in KNOWN]
    total = len(candidates)
    print(f"스캔 범위: {total}개 ID (예상 소요: {total*0.5/60:.1f}분)")
    print("게이지가 움직이면 아무 키나 누르세요!\n")

    last_id = None
    for i, can_id in enumerate(candidates):
        if not running: break
        _key_pressed.clear()
        sys.stdout.write(f"\r  [{i+1}/{total}] 0x{can_id:03X} 테스트 중...  ")
        sys.stdout.flush()

        send_for(ucan, can_id, bytes([0xFF]*8), 0.3)  # HIGH
        send_for(ucan, can_id, bytes([0x00]*8), 0.2)  # LOW (비교용)

        last_id = can_id
        if _key_pressed.is_set():
            print(f"\n\n!!! 키 감지! 마지막 ID: 0x{can_id:03X} !!!")
            return can_id

    print()
    return None

# ── 단계 2: 바이트 스캔 ────────────────────────────────────────────────────
def byte_scan(ucan, can_id):
    print(f"\n=== 0x{can_id:03X} 바이트 스캔 ===")
    print("게이지 움직이면 아무 키나 누르세요!\n")
    for b in range(8):
        if not running: break
        _key_pressed.clear()
        hi = bytearray(8); hi[b] = 0xFF
        lo = bytearray(8)
        sys.stdout.write(f"\r  byte[{b}]: 0xFF↔0x00  ")
        sys.stdout.flush()
        send_for(ucan, can_id, bytes(hi), 0.8)
        send_for(ucan, can_id, bytes(lo), 0.4)
        if _key_pressed.is_set():
            print(f"\n→ byte[{b}] 발견!")
            value_scan(ucan, can_id, b)
            return b
    print()
    return None

# ── 단계 3: 값 매핑 ────────────────────────────────────────────────────────
def value_scan(ucan, can_id, byte_idx):
    print(f"\n=== 0x{can_id:03X} byte[{byte_idx}] 값 매핑 (각 2초) ===")
    for val in [0xFF, 0xC0, 0x80, 0x40, 0x20, 0x00]:
        if not running: break
        data = bytearray(8); data[byte_idx] = val
        print(f"  0x{val:02X} ({val}) 전송중...", flush=True)
        send_for(ucan, can_id, bytes(data), 2.0)
    print(f"\n결과: 연료계 = 0x{can_id:03X} byte[{byte_idx}]")
    print(f"  full(0xFF=255) ~ empty(0x00=0) 또는 반대")

# ── 메인 ──────────────────────────────────────────────────────────────────
def main():
    print("=" * 50)
    print("연료계 CAN ID 자동 탐색")
    print("=" * 50)

    ucan = UCANInterface()
    try:
        ucan.connect()
        print("UCAN 연결 OK\n")
    except Exception as e:
        print(f"연결 실패: {e}"); sys.exit(1)

    try:
        found = fast_scan(ucan)
        if found and running:
            byte_scan(ucan, found)
        elif running:
            print("탐색 완료. 연료계 ID를 찾지 못했습니다.")
            print("→ 0x329의 다른 바이트일 수 있습니다. byte_scan(ucan, 0x329) 시도해보세요.")
    finally:
        ucan.close()

if __name__ == "__main__":
    main()
