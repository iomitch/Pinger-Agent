import logging
import subprocess

import httpx

from agent.config import settings

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(15.0, connect=10.0)
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0


def _get_git_hash() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()[:40]
    except Exception:
        return ""


def _get_public_ip() -> str:
    try:
        resp = httpx.get("https://ifconfig.me/ip", timeout=5.0)
        return resp.text.strip()[:64]
    except Exception:
        return ""


class AgentClient:
    def __init__(self) -> None:
        agent_headers = {"X-Api-Key": settings.pinger_api_key}
        git_hash = _get_git_hash()
        public_ip = _get_public_ip()
        if git_hash:
            agent_headers["X-Agent-Version"] = git_hash
        if public_ip:
            agent_headers["X-Agent-Ip"] = public_ip
        logger.info("Agent version=%s, public_ip=%s", git_hash[:8] or "unknown", public_ip or "unknown")

        self._client = httpx.AsyncClient(
            base_url=settings.pinger_server_url,
            headers=agent_headers,
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
