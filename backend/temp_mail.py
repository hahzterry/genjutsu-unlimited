"""Async temp mail wrapper — multi-provider with fallback.

Providers:
  1. 1secmail (default — fast, no auth needed)
  2. mail.tm (fallback — more reliable, needs token auth)

The TempMail interface (create / wait_for_link) stays identical across providers.
"""
import asyncio
import re
import random
import string
from typing import Callable, Awaitable
import httpx

# 1secmail config
SECMAIL_API = "https://www.1secmail.com/api/v1/"
SECMAIL_DOMAINS = ["1secmail.com", "1secmail.net", "1secmail.org", "esiix.com", "wwjmp.com"]

# mail.tm config
MAILTM_API = "https://api.mail.tm"

POLL_INTERVAL = 4
POLL_TIMEOUT = 180

LINK_RE = re.compile(r'https?://[^\s"\'<>]+(?:verify|confirm|activate)[^\s"\'<>]*', re.IGNORECASE)


class TempMail:
    """Async temp inbox with polling for a verification link. Multi-provider with fallback."""

    def __init__(self, client: httpx.AsyncClient | None = None):
        self.client = client or httpx.AsyncClient(timeout=30)
        self.login: str = ""
        self.domain: str = ""
        self.provider: str = "1secmail"
        self._mailtm_token: str | None = None
        self._mailtm_id: str | None = None

    async def close(self) -> None:
        await self.client.aclose()

    @property
    def address(self) -> str:
        return f"{self.login}@{self.domain}"

    async def create(self) -> str:
        """Generate a fresh mailbox. Tries 1secmail first, falls back to mail.tm."""
        try:
            return await self._create_1secmail()
        except Exception as e:
            await asyncio.sleep(1)
            try:
                return await self._create_mailtm()
            except Exception:
                raise RuntimeError(f"all temp mail providers failed: {e}")

    async def _create_1secmail(self) -> str:
        self.provider = "1secmail"
        self.login = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
        self.domain = random.choice(SECMAIL_DOMAINS)
        return self.address

    async def _create_mailtm(self) -> str:
        """Create a mail.tm inbox (more reliable, needs token auth)."""
        self.provider = "mail.tm"
        self.login = "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
        self.domain = "mail.tm"
        addr = self.address
        # Create account
        r = await self.client.post(f"{MAILTM_API}/accounts", json={"address": addr, "password": "TempPass123!"})
        r.raise_for_status()
        # Get auth token
        r = await self.client.post(f"{MAILTM_API}/token", json={"address": addr, "password": "TempPass123!"})
        r.raise_for_status()
        self._mailtm_token = r.json()["token"]
        self._mailtm_id = r.json()["id"]
        return addr

    async def get_messages(self) -> list[dict]:
        if self.provider == "1secmail":
            r = await self.client.get(SECMAIL_API, params={
                "action": "getMessages", "login": self.login, "domain": self.domain})
            r.raise_for_status()
            return r.json()
        else:  # mail.tm
            headers = {"Authorization": f"Bearer {self._mailtm_token}"}
            r = await self.client.get(f"{MAILTM_API}/messages", headers=headers)
            r.raise_for_status()
            return r.json().get("hydra:member", [])

    async def read_message(self, msg_id: int) -> dict:
        if self.provider == "1secmail":
            r = await self.client.get(SECMAIL_API, params={
                "action": "readMessage", "login": self.login, "domain": self.domain, "id": msg_id})
            r.raise_for_status()
            return r.json()
        else:  # mail.tm
            headers = {"Authorization": f"Bearer {self._mailtm_token}"}
            r = await self.client.get(f"{MAILTM_API}/messages/{msg_id}", headers=headers)
            r.raise_for_status()
            return r.json()

    async def wait_for_link(
        self,
        log: Callable[[str], Awaitable[None]] | None = None,
        link_re: re.Pattern = LINK_RE,
    ) -> str:
        async def _noop(_m: str) -> None:
            pass
        _log = log or _noop
        elapsed = 0
        seen: set[int] = set()
        while elapsed < POLL_TIMEOUT:
            try:
                msgs = await self.get_messages()
            except Exception as e:
                await _log(f"inbox poll error: {e}")
                await asyncio.sleep(POLL_INTERVAL)
                elapsed += POLL_INTERVAL
                continue
            for m in msgs:
                mid = m.get("id")
                if mid in seen:
                    continue
                seen.add(mid)
                await _log(f"mail from {m.get('from', '?')}: {m.get('subject', '?')}")
                full = await self.read_message(mid)
                body = full.get("htmlBody") or full.get("body") or full.get("textBody") or full.get("intro", "") or ""
                match = link_re.search(body)
                if match:
                    return match.group(0)
                match = re.search(r'https?://[^\s"\'<>]*higgsfield[^\s"\'<>]*', body, re.IGNORECASE)
                if match:
                    return match.group(0)
            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
        raise TimeoutError("no verification mail received within timeout")
