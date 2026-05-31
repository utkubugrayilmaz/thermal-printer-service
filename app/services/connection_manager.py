import asyncio
import time
from typing import Optional
from app.config import settings, ConnectionMode
from app.db.models import PrinterError
from app.core.logger import get_logger

logger = get_logger("connection_manager")


class ConnectionManager:
    def __init__(self):
        self._connected: bool = False
        self._mode: ConnectionMode = settings.connection_mode
        self._error: Optional[PrinterError] = None
        self._connect_time: Optional[float] = None
        self._reconnect_task: Optional[asyncio.Task] = None

        self._real_printer = None
        self._simulator = None

    async def connect(self, mode: Optional[ConnectionMode] = None) -> None:
        self._mode = mode or settings.connection_mode
        logger.info("Connecting", extra={"mode": self._mode})

        if self._mode == ConnectionMode.SIMULATION:
            from simulator.printer_simulator import simulator
            self._simulator = simulator
            await self._simulator.connect()

        elif self._mode == ConnectionMode.USB:
            await self._connect_usb()

        elif self._mode == ConnectionMode.ETHERNET:
            await self._connect_ethernet()

        self._connected = True
        self._error = None
        self._connect_time = time.monotonic()
        logger.info("Connected successfully", extra={"mode": self._mode})

    async def disconnect(self) -> None:
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()

        if self._mode == ConnectionMode.SIMULATION and self._simulator:
            await self._simulator.disconnect()

        elif self._real_printer:
            try:
                self._real_printer.close()
            except Exception:
                pass

        self._connected = False
        self._real_printer = None
        logger.info("Disconnected")

    def is_connected(self) -> bool:
        return self._connected

    @property
    def mode(self) -> ConnectionMode:
        return self._mode

    @property
    def error(self) -> Optional[PrinterError]:
        return self._error

    @property
    def uptime_seconds(self) -> float:
        if self._connect_time is None:
            return 0.0
        return time.monotonic() - self._connect_time

    async def check_hardware_status(self) -> Optional[PrinterError]:
        if self._mode == ConnectionMode.SIMULATION and self._simulator:
            return await self._simulator.check_status()
        # Gerçek yazıcı bağlantısı beklenmedik şekilde kopmuşsa reconnect başlat
        if self._real_printer is None and self._connected:
            self._connected = False
            if not self._reconnect_task or self._reconnect_task.done():
                self._reconnect_task = asyncio.create_task(self._reconnect_loop())
        return None

    async def print(self, content: str, content_type: str, copies: int = 1) -> None:
        if self._mode == ConnectionMode.SIMULATION and self._simulator:
            await self._simulator.print(content, content_type, copies)
        elif self._real_printer:
            await self._print_real(content, content_type, copies)
        else:
            # Yazıcı bağlantısı yok — reconnect döngüsünü tetikle
            self._connected = False
            if not self._reconnect_task or self._reconnect_task.done():
                self._reconnect_task = asyncio.create_task(self._reconnect_loop())
            raise RuntimeError(PrinterError.COMM_ERROR)

    def get_paper_info(self) -> tuple[float, float]:
        if self._mode == ConnectionMode.SIMULATION and self._simulator:
            return self._simulator.get_paper_remaining()
        return (-1.0, -1.0)

    async def _connect_usb(self) -> None:
        try:
            from escpos.printer import Usb  # type: ignore
            vid = int(settings.printer_usb_vendor_id, 16)
            pid = int(settings.printer_usb_product_id, 16)
            self._real_printer = Usb(vid, pid)
            logger.info("USB printer connected", extra={"vid": hex(vid), "pid": hex(pid)})
        except ImportError:
            logger.warning("python-escpos not installed, falling back to simulation")
            from simulator.printer_simulator import simulator
            self._simulator = simulator
            await self._simulator.connect()
            self._mode = ConnectionMode.SIMULATION
        except Exception as e:
            raise RuntimeError(PrinterError.COMM_ERROR) from e

    async def _connect_ethernet(self) -> None:
        try:
            from escpos.printer import Network  # type: ignore
            self._real_printer = Network(settings.printer_eth_host, settings.printer_eth_port)
            logger.info(
                "Ethernet printer connected",
                extra={"host": settings.printer_eth_host, "port": settings.printer_eth_port},
            )
        except ImportError:
            logger.warning("python-escpos not installed, falling back to simulation")
            from simulator.printer_simulator import simulator
            self._simulator = simulator
            await self._simulator.connect()
            self._mode = ConnectionMode.SIMULATION
        except Exception as e:
            raise RuntimeError(PrinterError.COMM_ERROR) from e

    async def _reconnect_loop(self) -> None:
        logger.info("Starting reconnect loop", extra={"mode": self._mode})
        for attempt in range(1, 6):
            backoff = settings.retry_backoff_base ** attempt
            logger.info("Reconnect attempt", extra={"attempt": attempt, "backoff_seconds": backoff})
            await asyncio.sleep(backoff)
            try:
                await self.connect(self._mode)
                logger.info("Reconnected successfully", extra={"attempt": attempt})
                return
            except Exception as exc:
                logger.warning("Reconnect attempt failed", extra={"attempt": attempt, "error": str(exc)})
        logger.error("Reconnect exhausted, giving up")

    async def _print_real(self, content: str, content_type: str, copies: int) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._sync_print, content, content_type, copies)

    def _sync_print(self, content: str, content_type: str, copies: int) -> None:
        p = self._real_printer
        for _ in range(copies):
            if content_type == "text":
                p.text(content + "\n\n\n")
            elif content_type == "image":
                import base64, io
                from PIL import Image  # type: ignore
                img = Image.open(io.BytesIO(base64.b64decode(content)))
                p.image(img)
            elif content_type == "qr":
                p.qr(content, size=6)
            p.cut()


connection_manager = ConnectionManager()