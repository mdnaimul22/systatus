from typing import List
from pydantic import BaseModel, Field


class SystemOverview(BaseModel):
    hostname: str = Field(..., description="System hostname")
    uptime_seconds: float = Field(..., description="System uptime in seconds")
    total_services_monitored: int = Field(..., description="Number of discovered custom services")
    active_services: int = Field(..., description="Number of currently running services")
    failed_services: int = Field(..., description="Number of failed services")
    inactive_services: int = Field(..., description="Number of stopped/inactive services")
    memory_total_bytes: int = Field(..., description="Total physical RAM in bytes")
    memory_available_bytes: int = Field(..., description="Available RAM in bytes")
    cpu_count: int = Field(..., description="Total logical CPU cores")
    load_average: List[float] = Field(default_factory=list, description="1, 5, 15 minute load averages")
