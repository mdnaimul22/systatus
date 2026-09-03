from fastapi import APIRouter, Depends

from src.schema import SystemOverview
from src.services import SystemManager, get_current_user

router = APIRouter(
    prefix="/api/system",
    tags=["System"],
    dependencies=[Depends(get_current_user)],
)


def get_system_manager() -> SystemManager:
    return SystemManager()


@router.get("/overview", response_model=SystemOverview, summary="Get system overview and status")
async def get_system_overview(
    manager: SystemManager = Depends(get_system_manager)
):
    """
    Returns host-level telemetry, uptime, resource counters, and summary of monitored services.
    """
    return await manager.get_system_overview()
