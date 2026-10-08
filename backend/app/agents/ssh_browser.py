"""Read a Kaspi product card through an optional browser on an SSH worker."""

from __future__ import annotations

import asyncio
import json
import re
from urllib.parse import urlsplit

from app.core.config import get_settings

_WORKER_PYTHON = "/home/project/tendr-browser-worker/venv/bin/python"
_WORKER_SCRIPT = "/home/project/tendr-browser-worker/worker.py"
_LOCK = asyncio.Semaphore(1)


def is_supported_product_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and parts.hostname == "kaspi.kz"
        and port in (None, 443)
        and not parts.username
        and not parts.password
        and parts.path.startswith("/shop/p/")
    )


async def read_product(url: str, *, city: str = "") -> dict | None:
    """Return rendered evidence or None; ordinary page readers remain fallback."""
    settings = get_settings()
    target = settings.browser_worker_ssh_target
    key = settings.browser_worker_ssh_key_file
    known_hosts = settings.browser_worker_ssh_known_hosts
    if not (target and key and known_hosts and is_supported_product_url(url)):
        return None
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*@[A-Za-z0-9.-]+", target):
        return None
    argv = [
        "ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
        "-o", f"UserKnownHostsFile={known_hosts}", "-o", "ConnectTimeout=8",
        "-i", key, target, _WORKER_PYTHON, _WORKER_SCRIPT,
    ]
    async with _LOCK:
        process = await asyncio.create_subprocess_exec(
            *argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            output, _error = await asyncio.wait_for(
                process.communicate(json.dumps({"url": url, "city": city}, ensure_ascii=False).encode()),
                timeout=45,
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            return None
        except asyncio.CancelledError:
            process.kill()
            await process.wait()
            raise
    if process.returncode != 0 or len(output) > 100_000:
        return None
    try:
        data = json.loads(output)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or data.get("url") != url or not data.get("product_title"):
        return None
    return data
