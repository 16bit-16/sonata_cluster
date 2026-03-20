"""
main.py
ETS2 -> YF Sonata 계기판 브릿지 메인 루프 (20Hz).
"""

import time
import logging
import signal
import sys
from telemetry_reader import TelemetryReader
from can_converter import CANConverter
from ucan_interface import UCANInterface
from config import TARGET_HZ

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

LOOP_INTERVAL = 1.0 / TARGET_HZ


def main():
    reader = TelemetryReader()
    converter = CANConverter()
    ucan = UCANInterface()

    shutdown = False

    def _on_signal(_sig, _frame):
        nonlocal shutdown
        log.info("Shutdown signal received")
        shutdown = True

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    log.info("Connecting to ETS2 plugin...")
    try:
        reader.connect()
    except Exception as e:
        log.error(f"Telemetry connect failed: {e}")
        sys.exit(1)

    log.info("Connecting to UCAN board...")
    try:
        ucan.connect()
    except Exception as e:
        log.error(f"UCAN connect failed: {e}")
        reader.close()
        sys.exit(1)

    log.info(f"Bridge running at {TARGET_HZ} Hz. Press Ctrl+C to stop.")

    while not shutdown:
        t0 = time.monotonic()

        try:
            telemetry = reader.read()
            messages = converter.convert(telemetry)
            ucan.send_all(messages)

            log.debug(
                f"spd={telemetry.speed_kmh:.1f}km/h  "
                f"rpm={telemetry.rpm:.0f}  "
                f"gear={telemetry.gear}  "
                f"temp={telemetry.coolant_temp:.0f}°C"
            )
        except Exception as e:
            log.exception(f"Loop error: {e}")

        elapsed = time.monotonic() - t0
        sleep_time = LOOP_INTERVAL - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)

    log.info("Shutting down...")
    ucan.close()
    reader.close()
    log.info("Done.")


if __name__ == "__main__":
    main()
