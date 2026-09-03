import os
import socket
from typing import Optional

from src.config import Settings, setup_logger, read_text, exists
from src.schema import SystemOverview
from src.services.service_manager import ServiceManager

logger = setup_logger(Settings.LOG_DIR / "service.log", name="app.services.system")


class SystemManager:
    """
    Business logic layer for system health, uptime, resource counters.
    """

    def __init__(self, service_manager: Optional[ServiceManager] = None):
        self.service_manager = service_manager or ServiceManager()

    async def get_system_overview(self) -> SystemOverview:
        """
        Gathers system-wide telemetry, load averages, memory, and service counts.
        """
        hostname = socket.gethostname()

        # Uptime
        uptime_seconds = 0.0
        try:
            if exists("/proc/uptime"):
                content = read_text("/proc/uptime")
                uptime_seconds = float(content.split()[0])
        except Exception as e:
            logger.warning(f"Could not read /proc/uptime: {e}")

        # Load average
        load_avg = []
        try:
            load_avg = list(os.getloadavg())
        except Exception as e:
            logger.debug(f"Could not read load average: {e}")
            load_avg = [0.0, 0.0, 0.0]

        # CPU count
        cpu_count = os.cpu_count() or 1

        # Memory info
        mem_total = 0
        mem_available = 0
        try:
            if exists("/proc/meminfo"):
                for line in read_text("/proc/meminfo").splitlines():
                    if line.startswith("MemTotal:"):
                        mem_total = int(line.split()[1]) * 1024
                    elif line.startswith("MemAvailable:"):
                        mem_available = int(line.split()[1]) * 1024
        except Exception as e:
            logger.warning(f"Could not read /proc/meminfo: {e}")

        # Services summary
        services = await self.service_manager.list_services()
        active_count = sum(1 for s in services if s.is_active)
        failed_count = sum(1 for s in services if s.is_failed)
        inactive_count = len(services) - active_count - failed_count

        return SystemOverview(
            hostname=hostname,
            uptime_seconds=uptime_seconds,
            total_services_monitored=len(services),
            active_services=active_count,
            failed_services=failed_count,
            inactive_services=inactive_count,
            memory_total_bytes=mem_total,
            memory_available_bytes=mem_available,
            cpu_count=cpu_count,
            load_average=load_avg
        )
