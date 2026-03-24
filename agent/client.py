import logging

import httpx

from agent.config import settings

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(15.0, connect=10.0)
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0


class AgentClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.pinger_server_url,
            headers={"X-Api-Key": settings.pinger_api_key},
            timeout=TIMEOUT,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        last_exc = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = await self._client.request(method, path, **kwargs)
                resp.raise_for_status()
                return resp.json()
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
                last_exc = exc
                if attempt < MAX_RETRIES:
                    import asyncio
                    wait = RETRY_BACKOFF * attempt
                    logger.warning("Request %s %s failed (attempt %d), retrying in %.1fs", method, path, attempt, wait)
                    await asyncio.sleep(wait)
            except httpx.HTTPStatusError as exc:
                logger.error("HTTP %d from %s %s: %s", exc.response.status_code, method, path, exc.response.text[:200])
                raise
        raise last_exc  # type: ignore[misc]

    async def whoami(self) -> dict:
        return await self._request("GET", "/api/agent/whoami")

    async def get_jobs(self) -> dict:
        return await self._request("GET", "/api/agent/jobs")

    async def post_measurements(self, measurements: list[dict]) -> dict:
        return await self._request("POST", "/api/agent/measurements", json={"measurements": measurements})

    async def post_traceroute(self, data: dict) -> dict:
        return await self._request("POST", "/api/agent/traceroute", json=data)
