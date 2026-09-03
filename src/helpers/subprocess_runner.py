import asyncio
from typing import List, Tuple, Optional
from src.config import Settings, setup_logger
from src.helpers.exceptions import AppError

logger = setup_logger(Settings.LOG_DIR / "helper.log", name="app.helpers.subprocess")


class CommandExecutionError(AppError):
    """Raised when a system command fails to execute or returns non-zero code."""
    def __init__(self, command: str, exit_code: int, stderr: str):
        super().__init__(
            message=f"Command '{command}' failed with exit code {exit_code}: {stderr.strip()}",
            status_code=500
        )
        self.command = command
        self.exit_code = exit_code
        self.stderr = stderr


async def run_command_async(
    args: List[str],
    timeout_seconds: float = 10.0
) -> Tuple[int, str, str]:
    """
    Executes a system executable asynchronously with argument list (preventing shell injection).

    Args:
        args: List of command-line arguments (first item must be the executable).
        timeout_seconds: Maximum execution time before raising TimeoutError.

    Returns:
        Tuple of (returncode, stdout, stderr)
    """
    if not args:
        raise ValueError("Cannot run empty command argument list")

    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout_b, stderr_b = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout_seconds
        )

        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        returncode = process.returncode if process.returncode is not None else -1

        return returncode, stdout, stderr

    except asyncio.TimeoutError:
        logger.error(f"Command timed out after {timeout_seconds}s: {' '.join(args)}")
        try:
            process.kill()
        except Exception as kill_err:
            logger.debug(f"Error killing process: {kill_err}")
        raise AppError(
            message=f"System command timed out after {timeout_seconds} seconds",
            status_code=504
        )
    except Exception as e:
        logger.error(f"Failed to execute command '{' '.join(args)}': {e}")
        raise AppError(
            message=f"Failed to execute command: {str(e)}",
            status_code=500
        )


async def is_passwordless_sudo_available() -> bool:
    """Checks whether the current process can execute sudo commands without a password."""
    try:
        process = await asyncio.create_subprocess_exec(
            "sudo", "-n", "true",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await asyncio.wait_for(process.communicate(), timeout=3.0)
        return process.returncode == 0
    except Exception:
        return False


async def verify_sudo_password(password: str) -> bool:
    """Verifies whether a provided sudo password is valid."""
    if not password:
        return False
    try:
        process = await asyncio.create_subprocess_exec(
            "sudo", "-S", "-k", "-p", "", "true",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr_b = await asyncio.wait_for(
            process.communicate(input=(password + "\n").encode("utf-8")),
            timeout=5.0
        )
        return process.returncode == 0
    except Exception:
        return False


async def run_privileged_command_async(
    args: List[str],
    sudo_password: Optional[str] = None,
    timeout_seconds: float = 15.0
) -> Tuple[int, str, str]:
    """
    Executes a privileged command with sudo.
    - If NOPASSWD is valid, executes directly.
    - If password is required and provided, pipes password to sudo -S.
    - If password is required and missing, raises SudoAuthenticationRequiredError.
    """
    from src.helpers.exceptions import SudoAuthenticationRequiredError, SudoInvalidPasswordError

    is_nopasswd = await is_passwordless_sudo_available()
    if is_nopasswd:
        full_cmd = ["sudo", *args]
        return await run_command_async(full_cmd, timeout_seconds=timeout_seconds)

    if not sudo_password:
        raise SudoAuthenticationRequiredError("Root privileges required to control system services.")

    full_cmd = ["sudo", "-S", "-p", "", *args]
    try:
        process = await asyncio.create_subprocess_exec(
            *full_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout_b, stderr_b = await asyncio.wait_for(
            process.communicate(input=(sudo_password + "\n").encode("utf-8")),
            timeout=timeout_seconds
        )

        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        returncode = process.returncode if process.returncode is not None else -1

        if returncode != 0:
            lower_err = stderr.lower()
            if "incorrect password" in lower_err or "authentication failure" in lower_err:
                raise SudoInvalidPasswordError()

        return returncode, stdout, stderr
    except asyncio.TimeoutError:
        raise AppError(f"Privileged command timed out after {timeout_seconds}s", status_code=504)
    except (SudoAuthenticationRequiredError, SudoInvalidPasswordError):
        raise
    except Exception as e:
        logger.error(f"Privileged execution error: {e}")
        raise AppError(f"Failed to execute privileged command: {e}", status_code=500)
