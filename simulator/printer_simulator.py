import asyncio
import random
from datetime import datetime, timezone
from typing import Optional
from app.db.models import PrinterError
from app.core.logger import get_logger

logger = get_logger("simulator")

ESC = b'\x1b'
GS  = b'\x1d'

CMD_INIT          = ESC + b'@'
CMD_ALIGN_LEFT    = ESC + b'a\x00'
CMD_ALIGN_CENTER  = ESC + b'a\x01'
CMD_ALIGN_RIGHT   = ESC + b'a\x02'
CMD_BOLD_ON       = ESC + b'E\x01'
CMD_BOLD_OFF      = ESC + b'E\x00'
CMD_FEED_LINE     = b'\n'
CMD_CUT_PAPER     = GS  + b'V\x41\x03'
CMD_QR_MODEL      = GS  + b'(k\x04\x00\x31\x41\x32\x00'
CMD_QR_SIZE       = GS  + b'(k\x03\x00\x31\x43\x06'
CMD_QR_CORRECTION = GS  + b'(k\x03\x00\x31\x45\x30'


class SimulatedPrinterState:

    def __init__(self, paper_meters: float = 50.0):
        self.paper_remaining_cm: float = paper_meters * 100
        self.is_cover_open: bool = False
        self.is_overheated: bool = False
        self.print_count: int = 0
        self.connected: bool = False
        self.busy: bool = False

    @property
    def paper_remaining_pct(self) -> float:
        initial = 5000.0  # 50m in cm
        return round(max(0.0, self.paper_remaining_cm / initial * 100), 1)


class PrinterSimulator:

    ERROR_RATE: float = 0.05

    def __init__(self):
        self.state = SimulatedPrinterState()
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        await asyncio.sleep(0.1)  # simulate USB/ETH handshake
        self.state.connected = True
        logger.info("Simulator connected", extra={"event": "connect"})

    async def disconnect(self) -> None:
        self.state.connected = False
        logger.info("Simulator disconnected", extra={"event": "disconnect"})

    def is_connected(self) -> bool:
        return self.state.connected

    async def check_status(self) -> Optional[PrinterError]:
        if self.state.paper_remaining_cm <= 0:
            return PrinterError.PAPER_OUT
        if self.state.is_cover_open:
            return PrinterError.COVER_OPEN
        if self.state.is_overheated:
            return PrinterError.OVERHEAT
        return None

    def _build_escpos_commands(self, content: str, content_type: str) -> bytes:
        buf = bytearray()
        buf += CMD_INIT

        if content_type == "text":
            buf += CMD_ALIGN_LEFT
            for line in content.splitlines():
                buf += line.encode("utf-8", errors="replace")
                buf += CMD_FEED_LINE
            buf += CMD_FEED_LINE * 3

        elif content_type == "image":
            buf += CMD_ALIGN_CENTER
            buf += b"[IMAGE DATA - raster bitmap would follow]\n"
            buf += CMD_FEED_LINE * 2

        elif content_type == "qr":
            data = content.encode("utf-8")
            length = len(data) + 3
            buf += CMD_QR_MODEL
            buf += CMD_QR_SIZE
            buf += CMD_QR_CORRECTION

            buf += GS + b'(k' + bytes([length & 0xFF, (length >> 8) & 0xFF]) + b'\x31\x50\x30'
            buf += data

            buf += GS + b'(k\x03\x00\x31\x51\x30'
            buf += CMD_FEED_LINE * 2

        buf += CMD_CUT_PAPER
        return bytes(buf)

    async def print(self, content: str, content_type: str, copies: int = 1) -> None:

        # --- CHAOS TEST BACKDOOR BAŞLANGICI ---
        if content_type == "text":
            if "FAIL_PAPER" in content:
                self.force_paper_out()
            elif "FAIL_HEAT" in content:
                self.force_overheat()
        # --- CHAOS TEST BACKDOOR BİTİŞİ ---

        async with self._lock:

            hw_error = await self.check_status()
            if hw_error:
                raise RuntimeError(hw_error)


            if random.random() < self.ERROR_RATE:
                raise RuntimeError(PrinterError.COMM_ERROR)

            self.state.busy = True
            try:
                for copy in range(copies):
                    commands = self._build_escpos_commands(content, content_type)
                    cmd_bytes = len(commands)


                    latency = min(cmd_bytes / 2048, 2.0)
                    await asyncio.sleep(latency)

                    lines = len(content.splitlines()) + 3  # +3 for header/footer
                    paper_used_cm = lines * 0.33           # ~3.3mm per line
                    self.state.paper_remaining_cm = max(
                        0.0, self.state.paper_remaining_cm - paper_used_cm
                    )
                    self.state.print_count += 1

                    logger.info(
                        "Page printed",
                        extra={
                            "event": "print",
                            "copy": copy + 1,
                            "total_copies": copies,
                            "content_type": content_type,
                            "escpos_bytes": cmd_bytes,
                            "paper_remaining_cm": round(self.state.paper_remaining_cm, 1),
                        },
                    )
            finally:
                self.state.busy = False

    def get_paper_remaining(self) -> tuple[float, float]:
        return self.state.paper_remaining_cm, self.state.paper_remaining_pct

    def get_print_count(self) -> int:
        return self.state.print_count


    def force_paper_out(self) -> None:
        self.state.paper_remaining_cm = 0.0

    def force_cover_open(self, open: bool = True) -> None:
        self.state.is_cover_open = open

    def force_overheat(self, hot: bool = True) -> None:
        self.state.is_overheated = hot


simulator = PrinterSimulator()
