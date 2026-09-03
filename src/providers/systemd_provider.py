import asyncio
import os
import re
from typing import Dict, List, Optional, Tuple

from src.config import Settings, setup_logger, exists, is_dir, is_file, list_files, read_text, write_text, delete
from src.helpers import (
    run_command_async,
    run_privileged_command_async,
    AppError,
    ValidationError,
    NotFoundError,
    PermissionDeniedError,
    SudoAuthenticationRequiredError,
    SudoInvalidPasswordError
)
from src.schema import ServiceScope, ServiceAction, ServiceStatus

logger = setup_logger(Settings.LOG_DIR / "provider.log", name="app.providers.systemd")

# Only allow safe unit name characters: letters, digits, '.', '-', '_', '@'
UNIT_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.@]+$")


def validate_unit_name(unit_name: str) -> str:
    """Validates that unit name conforms to safe systemd naming patterns."""
    clean_name = unit_name.strip()
    if not clean_name:
        raise ValidationError("Service unit name cannot be empty")
    if not UNIT_NAME_PATTERN.match(clean_name):
        raise ValidationError(
            f"Invalid service unit name '{clean_name}'. Only alphanumeric and . - _ @ characters are allowed."
        )
    return clean_name


class SystemdProvider:
    """
    Asynchronous systemd provider for inspecting and controlling systemd services.
    Handles both system and user scoped units without shell injection risks.
    """

    SYSTEMCTL_BIN = "/usr/bin/systemctl"

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or Settings

    def discover_custom_service_files(self) -> List[Tuple[str, ServiceScope, str]]:
        """
        Scans configured filesystem paths for custom .service unit files.
        Returns list of (unit_name, scope, filepath).
        """
        discovered = []

        # 1. User services (~/.config/systemd/user/*.service)
        for raw_dir in self.settings.USER_SERVICE_DIRS:
            if exists(raw_dir) and is_dir(raw_dir):
                for entry in list_files(raw_dir, "*.service"):
                    entry_path = str(entry)
                    if is_file(entry_path) or entry.is_symlink():
                        discovered.append((entry.name, ServiceScope.USER, entry_path))

        # 2. System custom services (/etc/systemd/system/*.service)
        for raw_dir in self.settings.SYSTEM_SERVICE_DIRS:
            if exists(raw_dir) and is_dir(raw_dir):
                for entry in list_files(raw_dir, "*.service"):
                    # Exclude generic dbus aliases or display-manager symlinks if vendor-bound
                    if entry.name.startswith("dbus-"):
                        continue
                    entry_path = str(entry)
                    if is_file(entry_path) or entry.is_symlink():
                        discovered.append((entry.name, ServiceScope.SYSTEM, entry_path))

        # Deduplicate while preserving order
        seen = set()
        unique_services = []
        for name, scope, filepath in discovered:
            key = (name, scope)
            if key not in seen:
                seen.add(key)
                unique_services.append((name, scope, filepath))

        return unique_services

    async def get_unit_properties(self, unit_name: str, scope: ServiceScope) -> Dict[str, str]:
        """
        Executes 'systemctl show' to extract key-value properties of a service.
        """
        clean_name = validate_unit_name(unit_name)
        cmd = [self.SYSTEMCTL_BIN]
        if scope == ServiceScope.USER:
            cmd.append("--user")

        properties = [
            "Id",
            "Description",
            "LoadState",
            "ActiveState",
            "SubState",
            "UnitFileState",
            "ExecMainPID",
            "MainPID",
            "MemoryCurrent",
            "CPUUsageNSec"
        ]

        cmd.extend([
            "show",
            clean_name,
            f"--property={','.join(properties)}",
            "--no-pager"
        ])

        returncode, stdout, stderr = await run_command_async(cmd, timeout_seconds=6.0)
        if returncode != 0:
            logger.warning(f"systemctl show failed for {clean_name} ({scope}): {stderr.strip()}")
            return {}

        props: Dict[str, str] = {}
        for line in stdout.splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                props[key.strip()] = value.strip()

        return props

    async def get_service_status(
        self,
        unit_name: str,
        scope: ServiceScope,
        file_path: Optional[str] = None
    ) -> ServiceStatus:
        """
        Fetches full parsed ServiceStatus for a given unit.
        """
        props = await self.get_unit_properties(unit_name, scope)

        active_state = props.get("ActiveState", "unknown")
        sub_state = props.get("SubState", "unknown")
        load_state = props.get("LoadState", "unknown")
        unit_file_state = props.get("UnitFileState")
        description = props.get("Description", "")
        unit_id = props.get("Id", unit_name)

        # Parse PID
        main_pid = 0
        raw_pid = props.get("MainPID") or props.get("ExecMainPID")
        if raw_pid and raw_pid.isdigit():
            main_pid = int(raw_pid)

        # Parse Memory
        memory_bytes = None
        raw_mem = props.get("MemoryCurrent")
        if raw_mem and raw_mem.isdigit() and raw_mem != "18446744073709551615":  # [not set] constant in systemd
            memory_bytes = int(raw_mem)

        # Parse CPU
        cpu_usage_nsec = None
        raw_cpu = props.get("CPUUsageNSec")
        if raw_cpu and raw_cpu.isdigit() and raw_cpu != "18446744073709551615":
            cpu_usage_nsec = int(raw_cpu)

        display_name = unit_name.removesuffix(".service")

        result = props.get("Result", "success")
        is_crash_loop = (sub_state == "auto-restart")
        is_failed = (
            active_state == "failed"
            or sub_state in ("failed", "auto-restart")
            or (result not in ("success", "") and active_state != "active")
        )

        return ServiceStatus(
            id=unit_id,
            name=display_name,
            description=description,
            load_state=load_state,
            active_state=active_state,
            sub_state=sub_state,
            unit_file_state=unit_file_state,
            main_pid=main_pid,
            memory_bytes=memory_bytes,
            cpu_usage_nsec=cpu_usage_nsec,
            scope=scope,
            is_active=(active_state == "active" and sub_state == "running"),
            is_failed=is_failed,
            is_crash_loop=is_crash_loop,
            unit_file_path=file_path or props.get("FragmentPath") or None
        )

    async def execute_service_action(
        self,
        unit_name: str,
        action: ServiceAction,
        scope: ServiceScope,
        sudo_password: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Executes a control action (start, stop, restart, reload) on a unit.
        Uses run_privileged_command_async for system units when elevation is needed.
        """
        clean_name = validate_unit_name(unit_name)
        cmd = [self.SYSTEMCTL_BIN]
        if scope == ServiceScope.USER:
            cmd.append("--user")
            cmd.extend([action.value, clean_name, "--no-pager"])
            returncode, stdout, stderr = await run_command_async(cmd, timeout_seconds=15.0)
        else:
            cmd.extend([action.value, clean_name, "--no-pager"])
            returncode, stdout, stderr = await run_privileged_command_async(
                cmd, sudo_password=sudo_password, timeout_seconds=15.0
            )

        if returncode == 0:
            return True, f"Successfully executed '{action.value}' on {clean_name}"
        else:
            err_msg = stderr.strip() or stdout.strip() or f"Exited with code {returncode}"
            logger.error(f"Action '{action.value}' failed on {clean_name}: {err_msg}")
            return False, err_msg

    async def daemon_reload(
        self,
        scope: ServiceScope,
        sudo_password: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Executes 'systemctl daemon-reload' for the given scope.
        """
        cmd = [self.SYSTEMCTL_BIN]
        if scope == ServiceScope.USER:
            cmd.append("--user")
            cmd.extend(["daemon-reload", "--no-pager"])
            returncode, stdout, stderr = await run_command_async(cmd, timeout_seconds=15.0)
        else:
            cmd.extend(["daemon-reload", "--no-pager"])
            returncode, stdout, stderr = await run_privileged_command_async(
                cmd, sudo_password=sudo_password, timeout_seconds=15.0
            )

        if returncode == 0:
            return True, "Daemon reloaded successfully"
        err_msg = stderr.strip() or stdout.strip() or f"Exited with code {returncode}"
        return False, err_msg

    async def disable_unit(
        self,
        unit_name: str,
        scope: ServiceScope,
        sudo_password: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Executes 'systemctl disable' for a unit.
        """
        clean_name = validate_unit_name(unit_name)
        cmd = [self.SYSTEMCTL_BIN]
        if scope == ServiceScope.USER:
            cmd.append("--user")
            cmd.extend(["disable", clean_name, "--no-pager"])
            returncode, stdout, stderr = await run_command_async(cmd, timeout_seconds=10.0)
        else:
            cmd.extend(["disable", clean_name, "--no-pager"])
            returncode, stdout, stderr = await run_privileged_command_async(
                cmd, sudo_password=sudo_password, timeout_seconds=10.0
            )

        if returncode == 0:
            return True, f"Unit {clean_name} disabled"
        return False, stderr.strip() or stdout.strip()

    async def reset_failed(
        self,
        unit_name: str,
        scope: ServiceScope,
        sudo_password: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Executes 'systemctl reset-failed' for a unit to clear failed memory states.
        """
        clean_name = validate_unit_name(unit_name)
        cmd = [self.SYSTEMCTL_BIN]
        if scope == ServiceScope.USER:
            cmd.append("--user")
            cmd.extend(["reset-failed", clean_name, "--no-pager"])
            returncode, stdout, stderr = await run_command_async(cmd, timeout_seconds=10.0)
        else:
            cmd.extend(["reset-failed", clean_name, "--no-pager"])
            returncode, stdout, stderr = await run_privileged_command_async(
                cmd, sudo_password=sudo_password, timeout_seconds=10.0
            )

        if returncode == 0:
            return True, f"Reset failed state for {clean_name}"
        return False, stderr.strip() or stdout.strip()

    async def read_unit_file(self, file_path: str) -> Tuple[str, bool]:
        """
        Reads unit file text content and checks write permission.
        Returns (content, is_writable).
        """
        if not exists(file_path) or not is_file(file_path):
            raise NotFoundError(resource=f"Unit file at '{file_path}'")

        content = read_text(file_path)
        is_writable = os.access(file_path, os.W_OK)
        return content, is_writable

    async def write_unit_file(
        self,
        file_path: str,
        content: str,
        sudo_password: Optional[str] = None
    ) -> None:
        """
        Writes content to unit file safely.
        Uses direct write if file is user-writable.
        If protected, writes to a temp file and elevates via sudo mv.
        """
        if not exists(file_path):
            raise NotFoundError(resource=f"Unit file at '{file_path}'")

        if os.access(file_path, os.W_OK):
            write_text(file_path, content)
            return

        # Write to safe temporary staging file
        tmp_staging = f"/tmp/.sys_status_edit_{os.getpid()}_{os.path.basename(file_path)}"
        try:
            write_text(tmp_staging, content)
            # Privileged move & permissions
            await run_privileged_command_async(
                ["mv", tmp_staging, file_path],
                sudo_password=sudo_password
            )
            await run_privileged_command_async(
                ["chmod", "644", file_path],
                sudo_password=sudo_password
            )
        except Exception:
            if exists(tmp_staging):
                delete(tmp_staging)
            raise

    async def remove_unit_file(
        self,
        file_path: str,
        sudo_password: Optional[str] = None
    ) -> None:
        """
        Deletes the unit file safely.
        Uses delete() if writable, or privileged sudo rm if protected.
        """
        if not exists(file_path):
            return

        parent_dir = str(os.path.dirname(file_path))
        if os.access(file_path, os.W_OK) and os.access(parent_dir, os.W_OK):
            delete(file_path)
            return

        # Attempt safe privileged rm if protected
        await run_privileged_command_async(
            ["rm", "-f", file_path],
            sudo_password=sudo_password,
            timeout_seconds=10.0
        )
