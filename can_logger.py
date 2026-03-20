"""
can_logger.py
UCAN 보드로부터 CAN 프레임을 수신하여 CSV로 저장하는 스니퍼.

사용법:
  python can_logger.py --port /dev/cu.usbserial-xxxx --out log.csv
  python can_logger.py --port /dev/cu.usbserial-xxxx --filter 0x386,0x4B0

분석:
  python can_logger.py --analyze log.csv
"""

import argparse
import csv
import time
import sys
import signal
import logging
import struct
from collections import defaultdict
from typing import Optional
import serial
from config import SERIAL_PORT, SERIAL_BAUD

log = logging.getLogger(__name__)

STX = 0xAA
ETX = 0x55

# UCAN RX 프레임: [STX][CH][ID_H][ID_L][DLC][D0..D7][ETX]
FRAME_HEADER_SIZE = 5   # STX + CH + ID(2) + DLC
FRAME_FOOTER_SIZE = 1   # ETX
MAX_DLC = 8


class UCANSniffer:
    """UCAN 보드에서 CAN 프레임을 수신."""

    def __init__(self, port: str, baud: int):
        self._ser = serial.Serial(port=port, baudrate=baud, timeout=0.1)
        self._buf = bytearray()

    def read_frames(self) -> list[tuple[int, int, bytes]]:
        """수신된 프레임 목록 반환: [(channel, can_id, data), ...]"""
        chunk = self._ser.read(256)
        if chunk:
            self._buf.extend(chunk)
        return self._parse_buf()

    def _parse_buf(self) -> list[tuple[int, int, bytes]]:
        frames = []
        while True:
            idx = self._buf.find(STX)
            if idx == -1:
                self._buf.clear()
                break
            if idx > 0:
                del self._buf[:idx]  # STX 이전 버려

            # 헤더가 충분히 쌓였는지 확인
            if len(self._buf) < FRAME_HEADER_SIZE:
                break

            dlc = self._buf[4]
            if dlc > MAX_DLC:
                del self._buf[0]   # 깨진 프레임, 1바이트 skip
                continue

            total = FRAME_HEADER_SIZE + dlc + FRAME_FOOTER_SIZE
            if len(self._buf) < total:
                break

            frame = bytes(self._buf[:total])
            del self._buf[:total]

            if frame[-1] != ETX:
                continue  # ETX 불일치, 버림

            ch = frame[1]
            can_id = (frame[2] << 8) | frame[3]
            data = frame[5:5 + dlc]
            frames.append((ch, can_id, data))

        return frames

    def close(self):
        self._ser.close()


class CANLogger:
    def __init__(self, out_path: str, id_filter: Optional[set[int]] = None):
        self._path = out_path
        self._filter = id_filter
        self._file = open(out_path, "w", newline="")
        self._writer = csv.writer(self._file)
        self._writer.writerow(["timestamp", "channel", "can_id", "dlc", "data_hex"])

    def write(self, ts: float, ch: int, can_id: int, data: bytes):
        if self._filter and can_id not in self._filter:
            return
        hex_str = data.hex(" ")
        self._writer.writerow([f"{ts:.6f}", ch, f"0x{can_id:03X}", len(data), hex_str])

    def close(self):
        self._file.close()


def run_logger(port: str, out_path: str, id_filter: Optional[set[int]]):
    sniffer = UCANSniffer(port, SERIAL_BAUD)
    logger = CANLogger(out_path, id_filter)
    count = 0
    shutdown = False

    def _sig(_s, _f):
        nonlocal shutdown
        shutdown = True

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    print(f"Logging to {out_path} ... Ctrl+C to stop")
    t_start = time.monotonic()

    while not shutdown:
        frames = sniffer.read_frames()
        ts = time.monotonic() - t_start
        for ch, can_id, data in frames:
            logger.write(ts, ch, can_id, data)
            count += 1
            print(f"  [{ts:8.3f}] CH{ch} 0x{can_id:03X}  {data.hex(' ')}")

    sniffer.close()
    logger.close()
    print(f"\nSaved {count} frames -> {out_path}")


# ---------------------------------------------------------------------------
# 분석 모드: CSV 로그에서 신호 패턴 추출
# ---------------------------------------------------------------------------

def analyze(csv_path: str):
    """CSV 로그를 읽어 CAN ID별 통계 및 변화량 요약 출력."""
    id_stats: dict[int, dict] = defaultdict(lambda: {
        "count": 0, "channels": set(), "samples": []
    })

    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            can_id = int(row["can_id"], 16)
            ch = int(row["channel"])
            data = bytes.fromhex(row["data_hex"].replace(" ", ""))
            st = id_stats[can_id]
            st["count"] += 1
            st["channels"].add(ch)
            if len(st["samples"]) < 200:
                st["samples"].append(data)

    print(f"\n{'CAN_ID':<8} {'CH':<5} {'frames':<8} {'DLC':<5}  변화 감지된 바이트")
    print("-" * 60)
    for can_id in sorted(id_stats):
        st = id_stats[can_id]
        samples = st["samples"]
        if not samples:
            continue
        dlc = len(samples[0])
        changed_bytes = _find_changing_bytes(samples)
        ch_str = "+".join(f"C{'BC'[c]}" for c in sorted(st["channels"]))
        print(f"0x{can_id:03X}   {ch_str:<5} {st['count']:<8} {dlc:<5}  bytes: {changed_bytes}")

    print()


def _find_changing_bytes(samples: list[bytes]) -> list[int]:
    """샘플 목록에서 값이 변한 바이트 인덱스를 반환."""
    if len(samples) < 2:
        return []
    ref = samples[0]
    changed = []
    for i in range(len(ref)):
        if any(s[i] != ref[i] for s in samples[1:] if i < len(s)):
            changed.append(i)
    return changed


# ---------------------------------------------------------------------------

def parse_filter(s: str) -> set[int]:
    return {int(x, 16) for x in s.split(",")}


def main():
    parser = argparse.ArgumentParser(description="UCAN CAN Bus Logger / Analyzer")
    sub = parser.add_subparsers(dest="cmd")

    log_p = sub.add_parser("log", help="CAN 트래픽 캡처")
    log_p.add_argument("--port", default=SERIAL_PORT)
    log_p.add_argument("--out", default="can_log.csv")
    log_p.add_argument("--filter", default=None, help="0x386,0x4B0 형식으로 필터")

    an_p = sub.add_parser("analyze", help="CSV 로그 분석")
    an_p.add_argument("csv", help="분석할 CSV 파일")

    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)

    if args.cmd == "log":
        id_filter = parse_filter(args.filter) if args.filter else None
        run_logger(args.port, args.out, id_filter)
    elif args.cmd == "analyze":
        analyze(args.csv)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
