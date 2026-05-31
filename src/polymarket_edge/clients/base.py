from __future__ import annotations

import asyncio
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from polymarket_edge.config import get_settings
from polymarket_edge.logging import get_logger

log = get_logger(__name__)


class APIClient:
    def __init__(self, base_url: str, timeout: float | None = None) -> None:
        settings = get_settings()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout or settings.REQUEST_TIMEOUT_SECONDS
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            headers={"User-Agent": "polymarket-edge/0.1"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=0.25, max=2),
        reraise=True,
    )
    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        return await self._client.request(method, path, **kwargs)

    async def get_json(self, path: str, params: dict[str, Any] | None = None,
                       headers: dict[str, str] | None = None) -> Any:
        try:
            response = await self._request("GET", path, params=params, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            log.warning("http_status_error", url=str(exc.request.url), status=exc.response.status_code)
        except httpx.HTTPError as exc:
            log.warning("http_request_error", url=f"{self.base_url}{path}", error=str(exc))
        except ValueError as exc:
            log.warning("json_decode_error", url=f"{self.base_url}{path}", error=str(exc))
        return None

    async def get_text(self, path: str, params: dict[str, Any] | None = None,
                        headers: dict[str, str] | None = None) -> str | None:
        """GET returning raw text (for RSS/XML feeds). None on any error."""
        try:
            response = await self._request("GET", path, params=params, headers=headers)
            response.raise_for_status()
            return response.text
        except httpx.HTTPStatusError as exc:
            log.warning("http_status_error", url=str(exc.request.url), status=exc.response.status_code)
        except httpx.HTTPError as exc:
            log.warning("http_request_error", url=f"{self.base_url}{path}", error=str(exc))
        return None

    async def post_json(self, path: str, payload: Any) -> Any:
        try:
            response = await self._request("POST", path, json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            log.warning("http_status_error", url=str(exc.request.url), status=exc.response.status_code)
        except httpx.HTTPError as exc:
            log.warning("http_request_error", url=f"{self.base_url}{path}", error=str(exc))
        except ValueError as exc:
            log.warning("json_decode_error", url=f"{self.base_url}{path}", error=str(exc))
        return None

    def run(self, coro):
        return asyncio.run(coro)

