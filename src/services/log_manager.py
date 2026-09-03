import json
from typing import AsyncGenerator, List, Optional

from src.config import Settings, setup_logger
from src.providers import JournalProvider, SystemdProvider
from src.schema import ServiceScope, StructuredLogEntry, LogQueryFilter
from src.services.service_manager import ServiceManager

logger = setup_logger(Settings.LOG_DIR / "service.log", name="app.services.logs")


class LogManager:
    """
    Business logic layer for retrieving and streaming structured logs.
    """

    def __init__(
        self,
        journal_provider: Optional[JournalProvider] = None,
        service_manager: Optional[ServiceManager] = None
    ):
        self.journal_provider = journal_provider or JournalProvider()
        self.service_manager = service_manager or ServiceManager()

    async def get_logs(
        self,
        unit_name: str,
        scope: Optional[ServiceScope],
        filter_params: LogQueryFilter
    ) -> List[StructuredLogEntry]:
        """
        Fetches structured logs for a service, resolving scope automatically if omitted.
        """
        service = await self.service_manager.get_service(unit_name, scope)
        return await self.journal_provider.fetch_structured_logs(
            unit_name=service.id,
            scope=service.scope,
            filter_params=filter_params
        )

    async def stream_sse_logs(
        self,
        unit_name: str,
        scope: Optional[ServiceScope],
        initial_lines: int = 20
    ) -> AsyncGenerator[str, None]:
        """
        Yields Server-Sent Events (SSE) formatted text for live streaming to browsers.
        """
        service = await self.service_manager.get_service(unit_name, scope)
        logger.info(f"Starting SSE live log stream for {service.id} ({service.scope})")

        async for entry in self.journal_provider.stream_structured_logs(
            unit_name=service.id,
            scope=service.scope,
            initial_lines=initial_lines
        ):
            yield f"data: {entry.model_dump_json()}\n\n"
