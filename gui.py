"""
gui.py - ETS2 Cluster Hub

tkinter GUI: ETS2 / BeamNG / Assetto Corsa / Clock 모드 전환
"""

import tkinter as tk
import threading
import queue
import time
import datetime
import logging

import can
from ucan_interface import UCANInterface
from can_converter import CANConverter
from telemetry_reader import TelemetryData

log = logging.getLogger(__name__)

# ── 색상 ─────────────────────────────────────────────────────────────────────
BG      = "#1a1a1a"
BG2     = "#252525"
BG3     = "#2f2f2f"
FG      = "#e0e0e0"
FG_DIM  = "#707070"
ACCENT  = "#3d8ef0"
GREEN   = "#4caf50"
RED     = "#f44336"
YELLOW  = "#ffb300"

MODES = ["ETS2", "BeamNG", "Assetto", "Clock"]


# ── 워커 스레드 ──────────────────────────────────────────────────────────────
class ClusterWorker(threading.Thread):
    """백그라운드: 텔레메트리 읽기 + CAN 전송 (100Hz)"""

    def __init__(self, mode: str, q: queue.Queue):
        super().__init__(daemon=True)
        self.mode = mode
        self._q   = q
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def _put(self, **kw):
        try:
            self._q.put_nowait(kw)
        except queue.Full:
            pass

    # ── 실행 ──────────────────────────────────────────────────────────────────
    def run(self):
        ucan = UCANInterface()
        conv = CANConverter()
        reader = None

        # UCAN 연결
        try:
            ucan.connect()
            self._put(usb="connected")
        except Exception as e:
            self._put(usb="error", msg=str(e))
            return

        # 게임 텔레메트리 연결
        if self.mode == "ETS2":
            from telemetry_reader import TelemetryReader
            reader = TelemetryReader()
            try:
                reader.connect()
                self._put(game="connected")
            except Exception as e:
                self._put(game="error", msg=str(e))

        elif self.mode == "BeamNG":
            from beamng_reader import BeamNGReader
            reader = BeamNGReader()
            try:
                reader.connect()
                self._put(game="connected")
            except Exception as e:
                self._put(game="error", msg=str(e))

        elif self.mode == "Assetto":
            from assetto_reader import AssettoCorsaReader
            reader = AssettoCorsaReader()
            try:
                reader.connect()
                self._put(game="connected")
            except Exception as e:
                self._put(game="error", msg=str(e))

        elif self.mode == "Clock":
            self._put(game="connected")

        # ── 메인 루프 (100Hz) ──────────────────────────────────────────────
        counter  = 0
        interval = 0.01

        while not self._stop.is_set():
            t0 = time.monotonic()

            data = self._clock_data() if self.mode == "Clock" \
                   else (reader.read() if reader else TelemetryData())

            try:
                for msg in conv.convert(data):
                    ucan.send(msg)
            except Exception as e:
                self._put(usb="error", msg=str(e))
                break

            # UI 업데이트 (10Hz)
            if counter % 10 == 0:
                self._put(
                    speed=data.speed_kmh,
                    rpm=data.rpm,
                    temp=data.coolant_temp,
                    gear=data.gear,
                )

            counter = (counter + 1) & 0xFF
            elapsed = time.monotonic() - t0
            rem = interval - elapsed
            if rem > 0:
                time.sleep(rem)

        if reader:
            reader.close()
        ucan.close()
        self._put(usb="disconnected", game="disconnected")

    # ── 시계 데이터 생성 ──────────────────────────────────────────────────────
    @staticmethod
    def _clock_data() -> TelemetryData:
        now = datetime.datetime.now()
        h, m, s = now.hour, now.minute, now.second
        d = TelemetryData()
        d.speed_ms     = h * 10 / 3.6          # 속도계: 시 × 10 km/h
        d.rpm          = m * 100                # 타코: 분 × 100 RPM
        d.coolant_temp = 60 + s * 50 / 60       # 수온: 60°C→110°C (60초 주기)
        d.gear         = 1                       # D
        d.engine_on    = True
        return d


# ── GUI ──────────────────────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Cluster Hub")
        self.configure(bg=BG)
        self.resizable(False, False)

        self._worker: ClusterWorker | None = None
        self._q: queue.Queue = queue.Queue(maxsize=100)
        self._current_mode: str | None = None

        self._build()
        self.after(100, self._tick)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI 구성 ──────────────────────────────────────────────────────────────
    def _build(self):
        # 타이틀
        tk.Label(self, text="CLUSTER HUB",
                 bg=BG, fg=FG, font=("Helvetica", 15, "bold")
                 ).pack(pady=(16, 8))

        # 모드 버튼
        btn_frame = tk.Frame(self, bg=BG)
        btn_frame.pack(padx=20, pady=4)
        self._btns: dict[str, tk.Button] = {}
        for mode in MODES:
            b = tk.Button(
                btn_frame, text=mode, width=9,
                bg=BG3, fg=FG, relief="flat",
                activebackground=ACCENT, activeforeground="white",
                font=("Helvetica", 10, "bold"),
                command=lambda m=mode: self._set_mode(m),
            )
            b.pack(side="left", padx=3)
            self._btns[mode] = b

        # 정지 버튼
        tk.Button(
            btn_frame, text="■ 정지", width=6,
            bg="#3a3a3a", fg="#aaaaaa", relief="flat",
            activebackground="#555", activeforeground="white",
            font=("Helvetica", 10),
            command=self._stop,
        ).pack(side="left", padx=(8, 0))

        # 구분선
        self._sep()

        # 상태 표시
        st = tk.Frame(self, bg=BG)
        st.pack(pady=6)

        tk.Label(st, text="USB", bg=BG, fg=FG_DIM,
                 font=("Helvetica", 9)).pack(side="left", padx=(0, 3))
        self._usb_dot   = tk.Label(st, text="●", bg=BG, fg=RED, font=("Helvetica", 13))
        self._usb_dot.pack(side="left")
        self._usb_lbl   = tk.Label(st, text="미연결", bg=BG, fg=FG_DIM, font=("Helvetica", 9))
        self._usb_lbl.pack(side="left", padx=(2, 24))

        tk.Label(st, text="Game", bg=BG, fg=FG_DIM,
                 font=("Helvetica", 9)).pack(side="left", padx=(0, 3))
        self._game_dot  = tk.Label(st, text="●", bg=BG, fg=RED, font=("Helvetica", 13))
        self._game_dot.pack(side="left")
        self._game_lbl  = tk.Label(st, text="미연결", bg=BG, fg=FG_DIM, font=("Helvetica", 9))
        self._game_lbl.pack(side="left", padx=(2, 0))

        # 구분선
        self._sep()

        # 게이지 표시
        g = tk.Frame(self, bg=BG)
        g.pack(padx=20, pady=6)
        self._speed_v = tk.StringVar(value="0")
        self._rpm_v   = tk.StringVar(value="0")
        self._temp_v  = tk.StringVar(value="0")
        self._gear_v  = tk.StringVar(value="N")

        for col, (label, var, unit) in enumerate([
            ("SPEED", self._speed_v, "km/h"),
            ("RPM",   self._rpm_v,   "rpm"),
            ("TEMP",  self._temp_v,  "°C"),
            ("GEAR",  self._gear_v,  ""),
        ]):
            f = tk.Frame(g, bg=BG2, padx=18, pady=10)
            f.grid(row=0, column=col, padx=4)
            tk.Label(f, text=label, bg=BG2, fg=FG_DIM,
                     font=("Helvetica", 8)).pack()
            tk.Label(f, textvariable=var, bg=BG2, fg=FG,
                     font=("Helvetica", 22, "bold"), width=5).pack()
            tk.Label(f, text=unit, bg=BG2, fg=FG_DIM,
                     font=("Helvetica", 8)).pack()

        # 구분선
        self._sep()

        # 상태 메시지
        self._msg_lbl = tk.Label(self, text="모드를 선택하세요",
                                  bg=BG, fg=FG_DIM, font=("Helvetica", 9))
        self._msg_lbl.pack(pady=(0, 14))

    def _sep(self):
        tk.Frame(self, bg="#333", height=1).pack(fill="x", padx=14, pady=4)

    # ── 모드 제어 ─────────────────────────────────────────────────────────────
    def _set_mode(self, mode: str):
        self._kill_worker()
        self._current_mode = mode
        self._highlight(mode)
        self._msg_lbl.config(text=f"{mode} 연결 중...")
        self._set_usb("disconnected")
        self._set_game("disconnected")

        self._q = queue.Queue(maxsize=100)
        self._worker = ClusterWorker(mode, self._q)
        self._worker.start()

    def _stop(self):
        self._kill_worker()
        self._current_mode = None
        self._highlight(None)
        self._msg_lbl.config(text="정지됨")
        self._set_usb("disconnected")
        self._set_game("disconnected")

    def _kill_worker(self):
        if self._worker and self._worker.is_alive():
            self._worker.stop()
            self._worker.join(timeout=2)
        self._worker = None

    def _highlight(self, active: str | None):
        for mode, btn in self._btns.items():
            if mode == active:
                btn.configure(bg=ACCENT, fg="white")
            else:
                btn.configure(bg=BG3, fg=FG)

    # ── 주기적 UI 갱신 ────────────────────────────────────────────────────────
    def _tick(self):
        while True:
            try:
                msg = self._q.get_nowait()
            except queue.Empty:
                break

            if "usb"  in msg:
                self._set_usb(msg["usb"])
            if "game" in msg:
                self._set_game(msg["game"])
            if "speed" in msg:
                self._speed_v.set(f"{msg['speed']:.0f}")
                self._rpm_v.set(f"{msg['rpm']:.0f}")
                self._temp_v.set(f"{msg['temp']:.0f}")
                g = msg["gear"]
                self._gear_v.set("R" if g < 0 else "N" if g == 0 else "D")
            if "msg" in msg:
                self._msg_lbl.config(text=msg["msg"])

        self.after(100, self._tick)

    def _set_usb(self, s: str):
        if s == "connected":
            self._usb_dot.config(fg=GREEN); self._usb_lbl.config(text="연결됨")
        elif s == "error":
            self._usb_dot.config(fg=YELLOW); self._usb_lbl.config(text="오류")
        else:
            self._usb_dot.config(fg=RED); self._usb_lbl.config(text="미연결")

    def _set_game(self, s: str):
        if s == "connected":
            self._game_dot.config(fg=GREEN); self._game_lbl.config(text="연결됨")
        elif s == "error":
            self._game_dot.config(fg=YELLOW); self._game_lbl.config(text="오류")
        else:
            self._game_dot.config(fg=RED); self._game_lbl.config(text="미연결")

    def _on_close(self):
        self._kill_worker()
        self.destroy()


# ── 진입점 ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    app = App()
    app.mainloop()
