import asyncio
import ipaddress
import logging
import re
import socket
import time

logger = logging.getLogger(__name__)

PING_RE = re.compile(r"time[=<]([0-9.]+)")

TRACEROUTE_LINE_RE = re.compile(r"^\s*(\d+)\s+(.*)$")
IP_RE = re.compile(r"\(([\dA-Fa-f:.]+)\)")
LATENCY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*ms")

# Track whether ICMP works in this environment
_icmp_available: bool | None = None


def _is_internal_ip(ip: str | None) -> bool:
    """Check if IP is Docker, private, or link-local — should be filtered from traceroute."""
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
        return addr.is_private or addr.is_link_local or addr.is_loopback
    except ValueError:
        return False


async def _icmp_ping(target: str) -> tuple[bool, float | None, str | None]:
    """ICMP ping using the system ping command."""
    try:
        process = await asyncio.create_subprocess_exec(
            "ping", "-c", "1", "-W", "1", target,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        output = (stdout or b"").decode("utf-8", errors="ignore")
        err_output = (stderr or b"").decode("utf-8", errors="ignore").strip()

        match = PING_RE.search(output)
        if process.returncode == 0 and match:
            return True, float(match.group(1)), None
        else:
            error = err_output or output.strip() or f"Ping failed with code {process.returncode}"
            return False, None, error
    except FileNotFoundError:
        return False, None, "ping executable not found"
    except Exception as exc:
        return False, None, str(exc)


async def _tcp_ping(target: str, ports: tuple[int, ...] = (443, 80, 22, 53)) -> tuple[bool, float | None, str | None]:
    """TCP connect ping — measures round-trip time via TCP handshake or rejection.

    A connection refused (RST) response is still a valid latency measurement —
    it proves the host is reachable and gives us the round-trip time.
    Only a timeout means the host is truly unreachable.
    """
    # Resolve hostname first
    try:
        ip = socket.gethostbyname(target)
    except socket.gaierror:
        return False, None, f"DNS resolution failed for {target}"

    for port in ports:
        try:
            start = time.monotonic()
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port), timeout=2.0,
            )
            elapsed = (time.monotonic() - start) * 1000  # ms
            writer.close()
            await writer.wait_closed()
            return True, round(elapsed, 2), None
        except ConnectionRefusedError:
            # Connection refused = host is alive, port just isn't open
            # The round-trip time is still valid
            elapsed = (time.monotonic() - start) * 1000
            return True, round(elapsed, 2), None
        except asyncio.TimeoutError:
            continue
        except OSError as exc:
            # Network unreachable, host unreachable, etc. — try next port
            if "Connection refused" in str(exc):
                elapsed = (time.monotonic() - start) * 1000
                return True, round(elapsed, 2), None
            continue

    return False, None, f"TCP connect failed on ports {ports}"


async def ping_target(target: str) -> tuple[bool, float | None, str | None]:
    """Ping with automatic ICMP → TCP fallback."""
    global _icmp_available

    # First call: test if ICMP works
    if _icmp_available is None:
        success, latency, error = await _icmp_ping(target)
        if success:
            _icmp_available = True
            return success, latency, error
        # ICMP failed — try TCP to distinguish "host down" from "ICMP blocked"
        tcp_success, tcp_latency, _ = await _tcp_ping(target)
        if tcp_success:
            # Host is reachable but ICMP is blocked — switch to TCP mode
            _icmp_available = False
            logger.info("ICMP blocked in this environment, switching to TCP ping")
            return tcp_success, tcp_latency, None
        # Both failed — host is probably down, stay in probe mode
        return False, None, error

    if _icmp_available:
        return await _icmp_ping(target)
    else:
        return await _tcp_ping(target)


async def run_traceroute(target: str, max_hops: int = 30) -> list[dict]:
    """Run traceroute and return parsed hop list."""
    try:
        process = await asyncio.create_subprocess_exec(
            "traceroute", "-I", "-w", "1", "-q", "5", "-m", str(max_hops), target,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        output = (stdout or b"").decode("utf-8", errors="ignore")

        raw_hops = []
        for line in output.splitlines():
            hop = _parse_hop_line(line)
            if hop:
                raw_hops.append(hop)

        # Filter out internal IPs and timeout-only hops, then renumber
        hops = []
        for hop in raw_hops:
            if _is_internal_ip(hop.get("ip_address")):
                continue
            # Skip hops that are pure timeouts (no IP, no latency)
            if hop.get("timeout") and not hop.get("ip_address"):
                continue
            hop["hop"] = len(hops) + 1
            hops.append(hop)
        return hops
    except Exception:
        return []


def _parse_hop_line(line: str) -> dict | None:
    match = TRACEROUTE_LINE_RE.match(line)
    if not match:
        return None

    hop_number = int(match.group(1))
    remainder = match.group(2).strip()
    latencies = [float(v) for v in LATENCY_RE.findall(remainder)]
    timeout = "*" in remainder and not latencies

    hostname = None
    ip_address = None

    ip_match = IP_RE.search(remainder)
    if ip_match:
        ip_address = ip_match.group(1)
        hostname_part = remainder[:ip_match.start()].strip()
        hostname_part = re.sub(r"^[\s*]+", "", hostname_part).strip()
        if hostname_part and hostname_part != ip_address:
            hostname = hostname_part
    elif remainder and not timeout:
        first_token = remainder.split()[0]
        try:
            import ipaddress as _ipa
            _ipa.ip_address(first_token)
            ip_address = first_token
        except ValueError:
            hostname = first_token

    if not hostname and ip_address:
        hostname = ip_address

    avg_latency = sum(latencies) / len(latencies) if latencies else None
    jitter = None
    if len(latencies) >= 2:
        diffs = [abs(latencies[i] - latencies[i - 1]) for i in range(1, len(latencies))]
        jitter = sum(diffs) / len(diffs)

    return {
        "hop": hop_number,
        "hostname": hostname,
        "ip_address": ip_address,
        "average_latency_ms": round(avg_latency, 2) if avg_latency is not None else None,
        "min_latency_ms": round(min(latencies), 2) if latencies else None,
        "max_latency_ms": round(max(latencies), 2) if latencies else None,
        "jitter_ms": round(jitter, 2) if jitter is not None else None,
        "sample_count": len(latencies),
        "timeout": timeout,
    }
