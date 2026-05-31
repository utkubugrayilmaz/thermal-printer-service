from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from enum import Enum


class ConnectionMode(str, Enum):
    USB = "usb"
    ETHERNET = "ethernet"
    SIMULATION = "simulation"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    app_name: str = "Thermal Printer Service"
    app_version: str = "1.0.0"
    debug: bool = False
    port: int = 3000

    connection_mode: ConnectionMode = ConnectionMode.SIMULATION
    printer_usb_vendor_id: str = "0x0519"
    printer_usb_product_id: str = "0x0001"
    printer_eth_host: str = "192.168.1.100"
    printer_eth_port: int = 9100

    max_retry_attempts: int = 3
    retry_backoff_base: float = 2.0   # seconds, exponential
    job_timeout_seconds: int = 30

    database_url: str = "sqlite:///./thermal_printer.db"

    paper_roll_initial_meters: float = 50.0
    avg_paper_per_print_cm: float = 10.0

    API_TOKEN: str = ""


settings = Settings()