"""Canonical API paths and signed requests for every bot command."""
import hashlib
import hmac
import time
import secrets
import httpx
from urllib.parse import urlsplit, urlunsplit
from bot.config import get_settings

class BotApiClient(httpx.AsyncClient):
    def __init__(self, *, telegram_id: int, **kwargs):
        super().__init__(**kwargs)
        self.telegram_id = telegram_id

    async def request(self, method, url, **kwargs):
        secret = get_settings().bot_api_secret
        if len(secret) < 32 or self.telegram_id <= 0: raise RuntimeError("BOT_AUTH_NOT_CONFIGURED")
        parts = urlsplit(str(url))
        if parts.scheme != "https" and parts.hostname not in {"localhost", "127.0.0.1", "api"}:
            raise RuntimeError("Bot backend must use HTTPS or a trusted local service")
        path = parts.path if parts.path.startswith("/api/") else "/api" + parts.path
        auth = kwargs.pop("auth", httpx.USE_CLIENT_DEFAULT)
        redirects = kwargs.pop("follow_redirects", httpx.USE_CLIENT_DEFAULT)
        request = self.build_request(method, urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment)), **kwargs)
        body = request.read()
        timestamp, nonce = str(int(time.time())), secrets.token_hex(16)
        target = request.url.raw_path.decode("ascii")
        canonical = f"{request.method}\n{target}\n{timestamp}\n{nonce}\n{self.telegram_id}\n{hashlib.sha256(body).hexdigest()}"
        request.headers.pop("X-Client-Id", None)
        request.headers.update({"X-Telegram-Id": str(self.telegram_id), "X-Bot-Timestamp": timestamp,
            "X-Bot-Nonce": nonce, "X-Bot-Signature": hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()})
        return await self.send(request, auth=auth, follow_redirects=redirects)
