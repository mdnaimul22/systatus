from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class ServiceScope(str, Enum):
    SYSTEM = "system"
    USER = "user"


class ServiceAction(str, Enum):
    START = "start"
    STOP = "stop"
    RESTART = "restart"
    RELOAD = "reload"


class ServiceStatus(BaseModel):
    id: str = Field(..., description="Full unit name e.g. omniroute.service")
    name: str = Field(..., description="Service display name")
    description: str = Field(default="", description="Unit description from systemd")
    load_state: str = Field(default="unknown", description="Loaded state e.g. loaded, not-found")
    active_state: str = Field(default="unknown", description="Active state e.g. active, inactive, failed")
    sub_state: str = Field(default="unknown", description="Sub state e.g. running, dead, exited")
    unit_file_state: Optional[str] = Field(default=None, description="Enabled state e.g. enabled, disabled, static")
    main_pid: int = Field(default=0, description="Process ID of the main daemon")
    memory_bytes: Optional[int] = Field(default=None, description="Current memory usage in bytes")
    cpu_usage_nsec: Optional[int] = Field(default=None, description="Total CPU time consumed in nanoseconds")
    scope: ServiceScope = Field(default=ServiceScope.SYSTEM, description="Scope: system or user")
    is_active: bool = Field(default=False, description="True if unit is actively running")
    is_failed: bool = Field(default=False, description="True if unit is in a failed state")
    is_crash_loop: bool = Field(default=False, description="True if unit is in auto-restart crash loop")
    unit_file_path: Optional[str] = Field(default=None, description="Path to unit file on filesystem")


class ServiceActionRequest(BaseModel):
    action: ServiceAction = Field(..., description="Action to perform: start, stop, restart, reload")
    scope: ServiceScope = Field(default=ServiceScope.SYSTEM, description="Scope: system or user")
    sudo_password: Optional[str] = Field(default=None, description="Optional sudo password for system units")


class ServiceActionResponse(BaseModel):
    success: bool
    service_id: str
    action: str
    message: str
    details: Optional[str] = None


class ServiceFileContent(BaseModel):
    unit_name: str
    path: str
    content: str
    is_writable: bool


class ServiceFileUpdateRequest(BaseModel):
    content: str = Field(..., description="New unit file configuration content")
    scope: Optional[ServiceScope] = None
    restart_after_update: bool = Field(default=False, description="Automatically restart service after reload")
    sudo_password: Optional[str] = Field(default=None, description="Optional sudo password for system units")


class ServiceFileOperationResponse(BaseModel):
    success: bool
    unit_name: str
    message: str
    path: Optional[str] = None


class SudoVerifyRequest(BaseModel):
    sudo_password: str = Field(..., description="Sudo password to verify")


class SudoVerifyResponse(BaseModel):
    valid: bool
    message: str
