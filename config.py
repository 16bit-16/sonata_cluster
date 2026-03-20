# ETS2 Cluster Bridge - Configuration

# ── IPC (ETS2 Plugin -> Python) ──────────────────────────────────────────────
import sys as _sys, os as _os
SOCKET_PATH = (
    _os.path.join(_os.environ.get("TEMP", "C:\\Temp"), "ets2_telemetry.sock")
    if _sys.platform == "win32" else "/tmp/ets2_telemetry.sock"
)
IPC_MODE = "socket"  # "socket" or "mmap"

# ── UCAN / CAN Bus ────────────────────────────────────────────────────────────
# FYSETC UCAN (CandleLight 펌웨어 / gs_usb) - 시리얼 포트 불필요
CAN_INTERFACE = "gs_usb"
CAN_BITRATE   = 500000   # 500 kbps (C-CAN)

# gs_usb는 channel이 정수 인덱스 (0 = 첫 번째 장치)
CAN_CHANNEL   = 0

# ── CAN Message IDs (YF Sonata 94003-3S170) ───────────────────────────────────
CAN_ID_SPEED    = 0x440   # 속도계 (byte[2] = km/h)
CAN_ID_SPEED2   = 0x280   # 속도계 보조 (byte[2] = 속도 연동, 없으면 바늘 안 움직임)
CAN_ID_RPM      = 0x316   # 타코미터 (byte[3] = RPM/62.5, counter in byte[1]&[4])
CAN_ID_GEAR     = 0x43F   # 기어 표시 (byte[1] 하위니블: P=0 R=7 N=6 D=5)
CAN_ID_COOLANT  = 0x329   # 수온계
CAN_ID_BRAKE    = 0x1F1   # ABS / 브레이크 경고등
CAN_ID_START    = 0x18F   # 시동 상태 (IG ON 유지용)

# ── Loop ──────────────────────────────────────────────────────────────────────
TARGET_HZ = 100           # 계기판 업데이트 주기 (Hz) - 속도계 100Hz 필요
