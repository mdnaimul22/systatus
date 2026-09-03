from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


PRIORITY_MAP = {
    0: "EMERGENCY",
    1: "ALERT",
    2: "CRITICAL",
    3: "ERROR",
    4: "WARNING",
    5: "NOTICE",
    6: "INFO",
    7: "DEBUG"
}


class StructuredLogEntry(BaseModel):
    timestamp: Optional[str] = Field(default=None, description="ISO formatted datetime string")
    realtime_usec: Optional[int] = Field(default=None, description="Microseconds since Unix epoch")
    priority: int = Field(default=6, description="Syslog priority number (0-7)")
    level: str = Field(default="INFO", description="Human-readable log level name")
    unit: Optional[str] = Field(default=None, description="Unit name e.g. omniroute.service")
    syslog_identifier: Optional[str] = Field(default=None, description="Syslog tag/binary name")
    pid: Optional[int] = Field(default=None, description="Process ID emitting the log")
    message: str = Field(default="", description="The log line message")
    raw: Optional[Dict[str, Any]] = Field(default=None, description="Full raw journal entry fields if requested")


class LogQueryFilter(BaseModel):
    lines: int = Field(default=100, ge=1, le=2000, description="Number of recent lines to retrieve")
    since: Optional[str] = Field(default=None, description="E.g. '1 hour ago', 'yesterday', '2026-09-01'")
    priority: Optional[int] = Field(default=None, ge=0, le=7, description="Filter logs by max priority level")
    reverse: bool = Field(default=False, description="Show newest logs first")
    grep: Optional[str] = Field(default=None, description="Pattern filter for message content")
