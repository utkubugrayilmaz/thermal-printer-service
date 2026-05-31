"""
Printer Simulator
-----------------
Mimics the behavior of a real ESC/POS thermal printer without hardware.
Implements the same interface as a real connection so services are unaware
of whether they're talking to real hardware or the simulator.
"""

import asyncio
import random
from datetime import datetime, timezone
from typing import Optional
from app.db.models import PrinterError
from app.core.logger import get_logger

logger = get_logger("simulator")

# ESC/POS command constants (real protocol)
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
    """Holds mutable hardware state."""

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
    """
    Simulates a Cashino KP-300/KP-301H/KP-302 thermal printer.
    Supports text, image (raster), and QR code content types.
    Introduces realistic latency and occasional transient errors.
    """

    # How often to simulate a transient error (0.0 = never, 0.1 = 10%)
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
        """Returns a hardware error if one exists, else None."""
        if self.state.paper_remaining_cm <= 0:
            return PrinterError.PAPER_OUT
        if self.state.is_cover_open:
            return PrinterError.COVER_OPEN
        if self.state.is_overheated:
            return PrinterError.OVERHEAT
        return None

    def _build_escpos_commands(self, content: str, content_type: str) -> bytes:
        """Builds real ESC/POS byte sequence for the given content."""
        buf = bytearray()
        buf += CMD_INIT

        if content_type == "text":
            buf += CMD_ALIGN_LEFT
            for line in content.splitlines():
                buf += line.encode("utf-8", errors="replace")
                buf += CMD_FEED_LINE
            buf += CMD_FEED_LINE * 3

        elif content_type == "image":
            # In simulation we just record the intent; real driver would
            # convert to raster via GS v 0 command
            buf += CMD_ALIGN_CENTER
            buf += b"[IMAGE DATA - raster bitmap would follow]\n"
            buf += CMD_FEED_LINE * 2

        elif content_type == "qr":
            data = content.encode("utf-8")
            length = len(data) + 3
            buf += CMD_QR_MODEL
            buf += CMD_QR_SIZE
            buf += CMD_QR_CORRECTION
            # GS ( k pL pH 31 50 30 <data>
            buf += GS + b'(k' + bytes([length & 0xFF, (length >> 8) & 0xFF]) + b'\x31\x50\x30'
            buf += data
            # GS ( k 3 0 31 51 30  — print QR
            buf += GS + b'(k\x03\x00\x31\x51\x30'
            buf += CMD_FEED_LINE * 2

        buf += CMD_CUT_PAPER
        return bytes(buf)

    async def print(self, content: str, content_type: str, copies: int = 1) -> None:
        """
        Simulate a print job. Raises RuntimeError with a PrinterError code
        if a hardware condition is detected.
        """
        async with self._lock:
            # Pre-flight hardware check
            hw_error = await self.check_status()
            if hw_error:
                raise RuntimeError(hw_error)

            # Random transient error simulation
            if random.random() < self.ERROR_RATE:
                raise RuntimeError(PrinterError.COMM_ERROR)

            self.state.busy = True
            try:
                for copy in range(copies):
                    commands = self._build_escpos_commands(content, content_type)
                    cmd_bytes = len(commands)

                    # Realistic print latency: ~2KB/s for a typical thermal head
                    latency = min(cmd_bytes / 2048, 2.0)
                    await asyncio.sleep(latency)

                    # Deduct paper usage
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
        """Returns (cm_remaining, pct_remaining)."""
        return self.state.paper_remaining_cm, self.state.paper_remaining_pct

    def get_print_count(self) -> int:
        return self.state.print_count

    # ── Test helpers ────────────────────────────────────────────────────────

    def force_paper_out(self) -> None:
        self.state.paper_remaining_cm = 0.0

    def force_cover_open(self, open: bool = True) -> None:
        self.state.is_cover_open = open

    def force_overheat(self, hot: bool = True) -> None:
        self.state.is_overheated = hot


# Module-level singleton — shared across the app
simulator = PrinterSimulator()
