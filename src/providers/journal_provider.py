import asyncio
import json
from datetime import datetime, timezone
from typing import AsyncGenerator, List, Optional

from src.config import Settings, setup_logger
from src.helpers import run_command_async, AppError
from src.providers.systemd_provider import validate_unit_name
from src.schema import ServiceScope, StructuredLogEntry, PRIORITY_MAP, LogQueryFilter

logger = setup_logger(Settings.LOG_DIR / "provider.log", name="app.providers.journal")


class JournalProvider:
    """
    Asynchronous provider for reading and streaming structured logs via journalctl.
    """

    JOURNALCTL_BIN = "/usr/bin/journalctl"

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or Settings

    def _parse_journal_line(self, line: str, unit_name: str) -> Optional[StructuredLogEntry]:
        """
        Parses a single JSON line output from 'journalctl -o json' into StructuredLogEntry.
        """
        line = line.strip()
        if not line:
            return None

        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            return None

        # Extract timestamp
        realtime_raw = raw.get("__REALTIME_TIMESTAMP")
        realtime_usec = None
        iso_timestamp = None
        if realtime_raw:
            try:
                realtime_usec = int(realtime_raw)
                dt = datetime.fromtimestamp(realtime_usec / 1_000_000.0, tz=timezone.utc)
                iso_timestamp = dt.isoformat()
            except (ValueError, TypeError, OverflowError) as parse_err:
                logger.debug(f"Could not parse realtime timestamp: {parse_err}")

        # Extract Priority & Level
        priority_raw = raw.get("PRIORITY", 6)
        try:
            priority = int(priority_raw)
        except (ValueError, TypeError):
            priority = 6
        level = PRIORITY_MAP.get(priority, "INFO")

        # Extract Message (sometimes byte array if non-utf8)
        raw_msg = raw.get("MESSAGE", "")
        if isinstance(raw_msg, list):
            try:
                message = bytes(raw_msg).decode("utf-8", errors="replace")
            except Exception:
                message = str(raw_msg)
        else:
            message = str(raw_msg)

        # Extract PID
        pid = None
        raw_pid = raw.get("_PID")
        if raw_pid and str(raw_pid).isdigit():
            pid = int(raw_pid)

        syslog_ident = raw.get("SYSLOG_IDENTIFIER") or raw.get("_COMM")

        return StructuredLogEntry(
            timestamp=iso_timestamp,
            realtime_usec=realtime_usec,
            priority=priority,
            level=level,
            unit=unit_name,
            syslog_identifier=syslog_ident,
            pid=pid,
            message=message
        )

    async def fetch_structured_logs(
        self,
        unit_name: str,
        scope: ServiceScope,
        filter_params: LogQueryFilter
    ) -> List[StructuredLogEntry]:
        """
        Retrieves recent structured logs for a unit.
        """
        clean_name = validate_unit_name(unit_name)
        cmd = [self.JOURNALCTL_BIN]
        if scope == ServiceScope.USER:
            cmd.append("--user")

        cmd.extend([
            "-u", clean_name,
            "-n", str(filter_params.lines),
            "-o", "json",
            "--no-pager"
        ])

        if filter_params.since:
            cmd.extend(["--since", filter_params.since])

        if filter_params.priority is not None:
            cmd.extend(["-p", str(filter_params.priority)])

        if filter_params.grep:
            cmd.extend(["-g", filter_params.grep])

        if filter_params.reverse:
            cmd.append("-r")

        returncode, stdout, stderr = await run_command_async(cmd, timeout_seconds=10.0)
        if returncode != 0:
            logger.error(f"journalctl query failed for {clean_name}: {stderr.strip()}")
            raise AppError(
                message=f"Failed to read journal logs for {clean_name}: {stderr.strip()}",
                status_code=500
            )

        entries: List[StructuredLogEntry] = []
        for line in stdout.splitlines():
            entry = self._parse_journal_line(line, clean_name)
            if entry:
                entries.append(entry)

        return entries

    async def stream_structured_logs(
        self,
        unit_name: str,
        scope: ServiceScope,
        initial_lines: int = 15
    ) -> AsyncGenerator[StructuredLogEntry, None]:
        """
        Streams live structured logs for a unit in real-time as an async generator.
        """
        clean_name = validate_unit_name(unit_name)
        cmd = [self.JOURNALCTL_BIN]
        if scope == ServiceScope.USER:
            cmd.append("--user")

        cmd.extend([
            "-u", clean_name,
            "-f",
            "-n", str(initial_lines),
            "-o", "json",
            "--no-pager"
        ])

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        try:
            while True:
                if process.stdout is None:
                    break
                line_b = await process.stdout.readline()
                if not line_b:
                    # Process exited or EOF reached
                    break
                line = line_b.decode("utf-8", errors="replace").strip()
                if line:
                    entry = self._parse_journal_line(line, clean_name)
                    if entry:
                        yield entry
        except asyncio.CancelledError:
            logger.info(f"Stream cancelled by client for {clean_name}")
        finally:
            try:
                process.terminate()
                await process.wait()
            except Exception as term_err:
                logger.debug(f"Process termination cleanup note: {term_err}")
