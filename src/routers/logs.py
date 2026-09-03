from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Path
from starlette.responses import StreamingResponse

from src.schema import StructuredLogEntry, ServiceScope, LogQueryFilter
from src.services import LogManager, get_current_user

router = APIRouter(
    prefix="/api/services",
    tags=["Logs"],
    dependencies=[Depends(get_current_user)],
)


def get_log_manager() -> LogManager:
    return LogManager()


@router.get("/{unit_name}/logs", response_model=List[StructuredLogEntry], summary="Get structured logs")
async def get_service_logs(
    unit_name: str = Path(..., description="Service unit name e.g. omniroute.service"),
    scope: Optional[ServiceScope] = Query(None, description="Scope: system or user"),
    lines: int = Query(100, ge=1, le=2000, description="Max lines to retrieve"),
    since: Optional[str] = Query(None, description="Time filter e.g. '1 hour ago'"),
    priority: Optional[int] = Query(None, ge=0, le=7, description="Max priority (0-7)"),
    grep: Optional[str] = Query(None, description="Text filter string"),
    reverse: bool = Query(False, description="Order descending"),
    manager: LogManager = Depends(get_log_manager)
):
    """
    Retrieves structured JSON logs via journalctl with optional filtering.
    """
    filter_params = LogQueryFilter(
        lines=lines,
        since=since,
        priority=priority,
        grep=grep,
        reverse=reverse
    )
    return await manager.get_logs(unit_name, scope, filter_params)


@router.get("/{unit_name}/logs/stream", summary="Stream live structured logs via SSE")
async def stream_service_logs(
    unit_name: str = Path(..., description="Service unit name e.g. omniroute.service"),
    scope: Optional[ServiceScope] = Query(None, description="Scope: system or user"),
    initial_lines: int = Query(20, ge=0, le=200, description="Initial historical lines to replay"),
    manager: LogManager = Depends(get_log_manager)
):
    """
    Streams live structured logs via Server-Sent Events (SSE) in real-time.
    """
    return StreamingResponse(
        manager.stream_sse_logs(unit_name, scope, initial_lines=initial_lines),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
