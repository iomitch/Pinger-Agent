import asyncio
import logging
from datetime import datetime, timezone

from agent.client import AgentClient
from agent.config import settings
from agent.executor import ping_target, run_traceroute

logger = logging.getLogger(__name__)


class AgentScheduler:
    def __init__(self, client: AgentClient) -> None:
        self._client = client
        self._jobs: list[dict] = []
        self._ping_interval: int = settings.ping_interval_override or 1
        self._buffer: list[dict] = []
        self._stop = asyncio.Event()

    async def run(self) -> None:
        # Verify connectivity
        info = await self._client.whoami()
        logger.info("Connected as '%s' (id=%d, location=%s)",
                     info["name"], info["ping_host_id"], info.get("location_label"))

        # Start tasks
        tasks = [
            asyncio.create_task(self._refresh_jobs_loop(), name="job-refresh"),
            asyncio.create_task(self._ping_loop(), name="ping-loop"),
            asyncio.create_task(self._flush_loop(), name="flush-loop"),
            asyncio.create_task(self._traceroute_loop(), name="traceroute-loop"),
        ]
        try:
            await self._stop.wait()
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def stop(self) -> None:
        self._stop.set()

    async def _refresh_jobs_loop(self) -> None:
        while not self._stop.is_set():
            try:
                data = await self._client.get_jobs()
                self._jobs = data.get("jobs", [])
                server_interval = data.get("ping_interval_seconds", 1)
                self._ping_interval = settings.ping_interval_override or server_interval
                logger.info("Refreshed %d jobs, interval=%ds", len(self._jobs), self._ping_interval)
            except Exception:
                logger.warning("Failed to refresh jobs", exc_info=True)
            await asyncio.sleep(60)

    async def _ping_loop(self) -> None:
        # Wait for first job refresh
        await asyncio.sleep(2)

        while not self._stop.is_set():
            if not self._jobs:
                await asyncio.sleep(5)
                continue

            started_at = asyncio.get_running_loop().time()
            now = datetime.now(timezone.utc)

            # Run all pings concurrently
            results = await asyncio.gather(
                *(ping_target(job["target"]) for job in self._jobs),
                return_exceptions=True,
            )

            for job, result in zip(self._jobs, results):
                if isinstance(result, Exception):
                    success, latency_ms, error = False, None, str(result)
                else:
                    success, latency_ms, error = result

                self._buffer.append({
                    "host_id": job["host_id"],
                    "latency_ms": latency_ms,
                    "success": success,
                    "error": error,
                    "recorded_at": now.isoformat(),
                })

            # Flush if buffer is large enough
            if len(self._buffer) >= settings.batch_size:
                await self._flush_buffer()

            elapsed = asyncio.get_running_loop().time() - started_at
            await asyncio.sleep(max(self._ping_interval - elapsed, 0.1))

    async def _flush_loop(self) -> None:
        """Periodically flush buffer even if batch_size not reached."""
        while not self._stop.is_set():
            await asyncio.sleep(settings.batch_flush_seconds)
            if self._buffer:
                await self._flush_buffer()

    async def _flush_buffer(self) -> None:
        if not self._buffer:
            return
        batch = self._buffer[:]
        self._buffer.clear()
        try:
            result = await self._client.post_measurements(batch)
            logger.debug("Posted %d measurements, accepted=%s", len(batch), result.get("accepted"))
        except Exception:
            logger.warning("Failed to post %d measurements, re-buffering", len(batch), exc_info=True)
            # Put them back at the front of the buffer
            self._buffer = batch + self._buffer

    async def _traceroute_loop(self) -> None:
        # Wait for jobs to load
        await asyncio.sleep(10)
        traceroute_available = None  # None = untested, True/False = detected

        while not self._stop.is_set():
            if traceroute_available is False:
                # Traceroute doesn't work in this environment — stop trying
                await asyncio.sleep(3600)
                continue

            for job in list(self._jobs):
                if self._stop.is_set():
                    break
                try:
                    hops = await run_traceroute(job["target"], max_hops=settings.traceroute_max_hops)

                    # First run: check if traceroute actually works
                    if traceroute_available is None:
                        has_real_hops = any(not h.get("timeout") for h in hops)
                        if not has_real_hops:
                            traceroute_available = False
                            logger.info("Traceroute not available in this environment (all hops timed out), disabling")
                            break
                        traceroute_available = True

                    if hops:
                        await self._client.post_traceroute({
                            "host_id": job["host_id"],
                            "generated_at": datetime.now(timezone.utc).isoformat(),
                            "hops": hops,
                        })
                        logger.debug("Traceroute for %s: %d hops", job["target"], len(hops))
                except Exception:
                    if traceroute_available is None:
                        traceroute_available = False
                        logger.info("Traceroute not available in this environment, disabling")
                        break
                    logger.debug("Traceroute failed for %s", job["target"], exc_info=True)

            await asyncio.sleep(settings.traceroute_interval_seconds)
