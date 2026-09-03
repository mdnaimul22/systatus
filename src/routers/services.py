from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Path, Header

from src.schema import (
    ServiceStatus,
    ServiceScope,
    ServiceActionRequest,
    ServiceActionResponse,
    ServiceFileContent,
    ServiceFileUpdateRequest,
    ServiceFileOperationResponse
)
from src.services import ServiceManager, get_current_user

router = APIRouter(
    prefix="/api/services",
    tags=["Services"],
    dependencies=[Depends(get_current_user)],
)


def get_service_manager() -> ServiceManager:
    return ServiceManager()


@router.get("", response_model=List[ServiceStatus], summary="List all discovered custom services")
async def list_services(
    manager: ServiceManager = Depends(get_service_manager)
):
    """
    Returns live status of all discovered custom systemd services across
    system and user configuration directories.
    """
    return await manager.list_services()


@router.get("/{unit_name}", response_model=ServiceStatus, summary="Get single service status")
async def get_service(
    unit_name: str = Path(..., description="Service unit name e.g. omniroute.service"),
    scope: Optional[ServiceScope] = Query(None, description="Optional scope: system or user"),
    manager: ServiceManager = Depends(get_service_manager)
):
    """
    Retrieves detailed properties, state, PID, memory, and CPU metrics for a service.
    """
    return await manager.get_service(unit_name, scope)


@router.post("/{unit_name}/action", response_model=ServiceActionResponse, summary="Perform lifecycle action")
async def perform_service_action(
    payload: ServiceActionRequest,
    unit_name: str = Path(..., description="Service unit name e.g. omniroute.service"),
    x_sudo_password: Optional[str] = Header(None, alias="X-Sudo-Password"),
    manager: ServiceManager = Depends(get_service_manager)
):
    """
    Executes start, stop, restart, or reload action on a systemd unit.
    Accepts sudo_password in payload or X-Sudo-Password header when modifying system units.
    """
    sudo_pwd = payload.sudo_password or x_sudo_password
    return await manager.perform_action(
        unit_name=unit_name,
        action=payload.action,
        scope=payload.scope,
        sudo_password=sudo_pwd
    )


@router.get("/{unit_name}/file", response_model=ServiceFileContent, summary="Get unit file configuration")
async def get_service_unit_file(
    unit_name: str = Path(..., description="Service unit name e.g. omniroute.service"),
    scope: Optional[ServiceScope] = Query(None, description="Optional scope: system or user"),
    manager: ServiceManager = Depends(get_service_manager)
):
    """
    Reads and returns the raw text content of the systemd .service unit file.
    """
    return await manager.get_unit_file(unit_name, scope)


@router.put("/{unit_name}/file", response_model=ServiceFileOperationResponse, summary="Update unit file configuration")
async def update_service_unit_file(
    payload: ServiceFileUpdateRequest,
    unit_name: str = Path(..., description="Service unit name e.g. omniroute.service"),
    x_sudo_password: Optional[str] = Header(None, alias="X-Sudo-Password"),
    manager: ServiceManager = Depends(get_service_manager)
):
    """
    Overwrites the unit file configuration, reloads systemd daemon, and optionally restarts the service.
    Accepts sudo_password in payload or X-Sudo-Password header when modifying system units.
    """
    sudo_pwd = payload.sudo_password or x_sudo_password
    return await manager.update_unit_file(
        unit_name=unit_name,
        content=payload.content,
        scope=payload.scope,
        restart_after_update=payload.restart_after_update,
        sudo_password=sudo_pwd
    )


@router.delete("/{unit_name}/file", response_model=ServiceFileOperationResponse, summary="Delete unit file")
async def delete_service_unit_file(
    unit_name: str = Path(..., description="Service unit name e.g. omniroute.service"),
    scope: Optional[ServiceScope] = Query(None, description="Optional scope: system or user"),
    x_sudo_password: Optional[str] = Header(None, alias="X-Sudo-Password"),
    manager: ServiceManager = Depends(get_service_manager)
):
    """
    Safely stops, disables, deletes the .service unit file, and reloads systemd.
    Accepts X-Sudo-Password header when deleting system units.
    """
    return await manager.delete_unit_file(unit_name, scope, sudo_password=x_sudo_password)
