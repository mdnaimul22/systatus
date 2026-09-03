import asyncio
from typing import List, Optional, Tuple

from src.config import Settings, setup_logger
from src.helpers import NotFoundError
from src.providers import SystemdProvider, validate_unit_name
from src.schema import (
    ServiceScope,
    ServiceAction,
    ServiceStatus,
    ServiceActionResponse,
    ServiceFileContent,
    ServiceFileOperationResponse
)

logger = setup_logger(Settings.LOG_DIR / "service.log", name="app.services.manager")


class ServiceManager:
    """
    Business logic layer for managing and monitoring systemd services.
    """

    def __init__(self, systemd_provider: Optional[SystemdProvider] = None):
        self.provider = systemd_provider or SystemdProvider()

    async def list_services(self) -> List[ServiceStatus]:
        """
        Discovers all custom unit files across system and user scopes,
        then concurrently queries their live systemd states.
        """
        discovered = self.provider.discover_custom_service_files()
        if not discovered:
            return []

        tasks = [
            self.provider.get_service_status(unit_name, scope, file_path)
            for unit_name, scope, file_path in discovered
        ]

        # Fetch statuses concurrently
        statuses: List[ServiceStatus] = await asyncio.gather(*tasks, return_exceptions=False)
        # Sort: active first, then alphabetically by name
        statuses.sort(key=lambda s: (not s.is_active, s.name.lower()))
        return statuses

    async def get_service(
        self,
        unit_name: str,
        scope: Optional[ServiceScope] = None
    ) -> ServiceStatus:
        """
        Retrieves status for a single service. If scope is not provided,
        attempts user scope first if found in user dir, else system scope.
        """
        clean_name = validate_unit_name(unit_name)
        unit_canonical = clean_name if clean_name.endswith(".service") else f"{clean_name}.service"
        discovered = self.provider.discover_custom_service_files()

        target_scope = scope
        file_path = None

        for name, sc, path in discovered:
            cand_canonical = name if name.endswith(".service") else f"{name}.service"
            if cand_canonical.lower() == unit_canonical.lower():
                if target_scope is None or sc == target_scope:
                    target_scope = sc
                    file_path = path
                    break

        if target_scope is None:
            # Default to system scope if not explicitly found in custom scan
            target_scope = ServiceScope.SYSTEM

        status = await self.provider.get_service_status(unit_canonical, target_scope, file_path)
        if status.load_state == "not-found" and not file_path:
            raise NotFoundError(resource=f"Service '{clean_name}'")

        return status

    async def perform_action(
        self,
        unit_name: str,
        action: ServiceAction,
        scope: Optional[ServiceScope] = None,
        sudo_password: Optional[str] = None
    ) -> ServiceActionResponse:
        """
        Triggers a lifecycle action (start, stop, restart, reload) on a service.
        """
        service = await self.get_service(unit_name, scope)
        success, message = await self.provider.execute_service_action(
            unit_name=service.id,
            action=action,
            scope=service.scope,
            sudo_password=sudo_password
        )

        return ServiceActionResponse(
            success=success,
            service_id=service.id,
            action=action.value,
            message=message
        )

    async def get_unit_file(
        self,
        unit_name: str,
        scope: Optional[ServiceScope] = None
    ) -> ServiceFileContent:
        """
        Reads and returns the unit file text content and write permission status.
        """
        service = await self.get_service(unit_name, scope)
        if not service.unit_file_path:
            raise NotFoundError(resource=f"Unit file path for '{unit_name}'")

        content, is_writable = await self.provider.read_unit_file(service.unit_file_path)
        return ServiceFileContent(
            unit_name=service.id,
            path=service.unit_file_path,
            content=content,
            is_writable=is_writable
        )

    async def update_unit_file(
        self,
        unit_name: str,
        content: str,
        scope: Optional[ServiceScope] = None,
        restart_after_update: bool = False,
        sudo_password: Optional[str] = None
    ) -> ServiceFileOperationResponse:
        """
        Updates unit file content, reloads daemon, and optionally restarts service.
        """
        service = await self.get_service(unit_name, scope)
        if not service.unit_file_path:
            raise NotFoundError(resource=f"Unit file path for '{unit_name}'")

        # 1. Write file
        await self.provider.write_unit_file(service.unit_file_path, content, sudo_password=sudo_password)
        logger.info(f"Unit file updated for {service.id} at {service.unit_file_path}")

        # 2. Daemon reload
        await self.provider.daemon_reload(service.scope, sudo_password=sudo_password)

        # 3. Optional restart
        restart_msg = ""
        if restart_after_update and service.is_active:
            _, re_info = await self.provider.execute_service_action(
                service.id, ServiceAction.RESTART, service.scope, sudo_password=sudo_password
            )
            restart_msg = f" | Restart: {re_info}"

        return ServiceFileOperationResponse(
            success=True,
            unit_name=service.id,
            message=f"Unit file updated and daemon reloaded{restart_msg}",
            path=service.unit_file_path
        )

    async def delete_unit_file(
        self,
        unit_name: str,
        scope: Optional[ServiceScope] = None,
        sudo_password: Optional[str] = None
    ) -> ServiceFileOperationResponse:
        """
        Safely stops, disables, deletes the unit file, and reloads systemd.
        """
        service = await self.get_service(unit_name, scope)
        if not service.unit_file_path:
            raise NotFoundError(resource=f"Unit file path for '{unit_name}'")

        target_path = service.unit_file_path

        # 1. Stop if running
        if service.is_active:
            logger.info(f"Stopping service {service.id} before deletion...")
            await self.provider.execute_service_action(
                service.id, ServiceAction.STOP, service.scope, sudo_password=sudo_password
            )

        # 2. Disable unit
        logger.info(f"Disabling service {service.id}...")
        await self.provider.disable_unit(service.id, service.scope, sudo_password=sudo_password)

        # 3. Remove file
        logger.info(f"Removing unit file {target_path}...")
        await self.provider.remove_unit_file(target_path, sudo_password=sudo_password)

        # 4. Reload daemon & reset failed
        await self.provider.daemon_reload(service.scope, sudo_password=sudo_password)
        await self.provider.reset_failed(service.id, service.scope, sudo_password=sudo_password)

        return ServiceFileOperationResponse(
            success=True,
            unit_name=service.id,
            message=f"Service '{service.id}' stopped, disabled, and file deleted successfully",
            path=target_path
        )
