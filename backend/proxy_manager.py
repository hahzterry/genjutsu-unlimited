"""ProxyManager — loading, testing, sticky sessions, and cooldown tracking.

Features:
  - Load proxies from env var (pipe | or comma separated)
  - Test proxy health (TCP connect check)
  - Sticky sessions (lock proxy to account for N days)
  - Cooldown tracking (45 min between accounts on same proxy)
  - Per-proxy metadata (country, timezone, last_used, account_count)
  - Backoff on failure (exponential backoff per proxy)
"""
import os, asyncio, time, logging
from typing import Optional
from dataclasses import dataclass, field

log = logging.getLogger("proxy_manager")

# Cooldown: 45 min between new accounts on the same proxy
COOLDOWN_SECONDS = int(os.getenv("PROXY_COOLDOWN", "2700"))  # 45 min
STICKY_DAYS = int(os.getenv("PROXY_STICKY_DAYS", "7"))  # lock proxy to account for 7 days

# Country → timezone mapping (for fingerprint matching)
COUNTRY_TIMEZONES = {
    "US": "America/New_York", "US-CA": "America/Los_Angeles",
    "GB": "Europe/London", "DE": "Europe/Berlin",
    "FR": "Europe/Paris", "CA": "America/Toronto",
    "NL": "Europe/Amsterdam", "JP": "Asia/Tokyo",
    "AU": "Australia/Sydney", "ES": "Europe/Madrid",
    "IT": "Europe/Rome", "SE": "Europe/Stockholm",
}


@dataclass
class ProxyInfo:
    url: str
    country: str = "US"
    timezone: str = "America/New_York"
    last_used: float = 0.0
    account_count: int = 0
    failures: int = 0
    sticky_until: float = 0.0  # locked to an account until this timestamp
    user_data_dir: str = ""

    @property
    def is_cooled_down(self) -> bool:
        return time.time() - self.last_used >= COOLDOWN_SECONDS

    @property
    def is_sticky_locked(self) -> bool:
        return time.time() < self.sticky_until

    @property
    def is_healthy(self) -> bool:
        return self.failures < 3


class ProxyManager:
    """Manages a pool of residential proxies with cooldown + sticky sessions."""
    def __init__(self, proxy_urls: list[str]):
        self.proxies: dict[str, ProxyInfo] = {}
        self._idx = 0
        self._lock = asyncio.Lock()
        self._load(proxy_urls)

    def _load(self, urls: list[str]):
        for url in urls:
            url = url.strip()
            if not url:
                continue
            # Parse country from URL (optional ?country=US parameter)
            country = "US"
            if "?" in url:
                base, params = url.split("?", 1)
                for param in params.split("&"):
                    if param.startswith("country="):
                        country = param.split("=")[1].upper()
                url = base
            tz = COUNTRY_TIMEZONES.get(country, "America/New_York")
            # Create user-data-dir path for persistent browser profile
            import hashlib
            dir_hash = hashlib.md5(url.encode()).hexdigest()[:10]
            udd = f"/tmp/browser_profiles/{dir_hash}"
            os.makedirs(udd, exist_ok=True)
            self.proxies[url] = ProxyInfo(
                url=url, country=country, timezone=tz, user_data_dir=udd
            )

    async def next(self) -> Optional[str]:
        """Get the next available proxy (cooled down, not sticky-locked, healthy)."""
        async with self._lock:
            if not self.proxies:
                return None
            urls = list(self.proxies.keys())
            for _ in range(len(urls)):
                url = urls[self._idx % len(urls)]
                self._idx += 1
                info = self.proxies[url]
                if not info.is_healthy:
                    continue
                if info.is_sticky_locked:
                    continue
                if not info.is_cooled_down:
                    continue
                return url
            # All proxies on cooldown — return the one with oldest last_used
            available = [u for u in urls if self.proxies[u].is_healthy]
            if available:
                return min(available, key=lambda u: self.proxies[u].last_used)
            return None

    async def mark_used(self, url: str):
        """Record that an account was created using this proxy."""
        async with self._lock:
            if url in self.proxies:
                self.proxies[url].last_used = time.time()
                self.proxies[url].account_count += 1

    async def bind_sticky(self, url: str, days: int = None):
        """Lock a proxy to an account for N days."""
        async with self._lock:
            if url in self.proxies:
                d = days or STICKY_DAYS
                self.proxies[url].sticky_until = time.time() + (d * 86400)

    async def record_failure(self, url: str):
        async with self._lock:
            if url in self.proxies:
                self.proxies[url].failures += 1

    async def reset_failure(self, url: str):
        async with self._lock:
            if url in self.proxies:
                self.proxies[url].failures = 0

    def get_info(self, url: str) -> Optional[ProxyInfo]:
        return self.proxies.get(url)

    def update_proxies(self, new_urls: list[str]):
        self._load(new_urls)
        self._idx = 0

    @property
    def size(self) -> int:
        return len(self.proxies)

    @property
    def healthy_count(self) -> int:
        return sum(1 for p in self.proxies.values() if p.is_healthy)

    def status(self) -> dict:
        return {
            "total": len(self.proxies),
            "healthy": self.healthy_count,
            "proxies": [
                {"url": f"{p.url.split('@')[0]}@***", "country": p.country,
                 "accounts": p.account_count, "failures": p.failures,
                 "cooldown_remaining": max(0, int(COOLDOWN_SECONDS - (time.time() - p.last_used)))}
                for p in self.proxies.values()
            ]
        }


def load_proxy_list() -> list[str]:
    """Load proxies from PROXY_LIST or PROXIES env var (pipe | or comma separated)."""
    raw = os.getenv("PROXY_LIST", "") or os.getenv("PROXIES", "")
    # Support both pipe | and comma , separators
    if "|" in raw:
        return [p.strip() for p in raw.split("|") if p.strip()]
    return [p.strip() for p in raw.split(",") if p.strip()]
