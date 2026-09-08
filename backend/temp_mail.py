"""Async 1secmail wrapper — generates a temp inbox and polls for the verification link.

1secmail API (https://www.1secmail.com/api/v1/):
  ?action=genRandomMailbox            -> ["xyz@domain.com", ...]
  ?action=getMessages&login=&domain=  -> [{id, from, subject, date}]
  ?action=readMessage&login=&domain=&id= -> {body, textBody, htmlBody}

NOTE: if 1secmail is unreachable, swap DOMAINS/API for mail.tm or guerrillamail —
the TempMail interface (create / wait_for_link) stays identical.
"""
import asyncio
import re
import random
import string
from typing import Callable
import httpx

API = "https://www.1secmail.com/api/v1/"
DOMAINS = ["1secmail.com", "1secmail.net", "1secmail.org", "esiix.com", "wwjmp.com"]
POLL_INTERVAL = 4   # seconds between inbox checks
POLL_TIMEOUT = 180  # 3 min max wait for verification mail

LINK_RE = re.compile(r'https?://[^\s"\'<>]+(?:verify|confirm|activate)[^\s"\'<>]*', re.IGNORECASE)


class TempMail:
    """Async temp inbox with polling for a verification link."""

    def __init__(self, client: httpx.AsyncClient | None = None):
        self.client = client or httpx.AsyncClient(timeout=30)
        self.login: str = ""
        self.domain: str = ""

    async def close(self) -> None:
        await self.client.aclose()

    @property
    def address(self) -> str:
        return f"{self.login}@{self.domain}"

    async def create(self) -> str:
        """Generate a fresh random mailbox."""
        self.login = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
        self.domain = random.choice(DOMAINS)
        return self.address

    async def get_messages(self) -> list[dict]:
        r = await self.client.get(API, params={
            "action": "getMessages",
            "login":  self.login,
            "domain": self.domain,
        })
        r.raise_for_status()
        return r.json()

    async def read_message(self, msg_id: int) -> dict:
        r = await self.client.get(API, params={
            "action": "readMessage",
            "login":  self.login,
            "domain": self.domain,
            "id":     msg_id,
        })
        r.raise_for_status()
        return r.json()

    async def wait_for_link(
        self,
        log: Callable[[str], None] = lambda m: None,
        link_re: re.Pattern = LINK_RE,
    ) -> str:
        """Poll the inbox until a verification link arrives. Returns the link."""
        elapsed = 0
        seen: set[int] = set()
        while elapsed < POLL_TIMEOUT:
            try:
                msgs = await self.get_messages()
            except Exception as e:
                log(f"inbox poll error: {e}")
                await asyncio.sleep(POLL_INTERVAL)
                elapsed += POLL_INTERVAL
                continue

            for m in msgs:
                if m["id"] in seen:
                    continue
                seen.add(m["id"])
                log(f"mail from {m.get('from')}: {m.get('subject')}")
                full = await self.read_message(m["id"])
                body = full.get("htmlBody") or full.get("body") or full.get("textBody") or ""
                match = link_re.search(body)
                if match:
                    return match.group(0)
                match = re.search(r'https?://[^\s"\'<>]*higgsfield[^\s"\'<>]*', body, re.IGNORECASE)
                if match:
                    return match.group(0)
            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
        raise TimeoutError("no verification mail received within timeout")
