"""Async temp mail wrapper — multi-provider with fallback.

Providers:
  1. mail.tm   (default — real IMAP-less REST API, does not go down often)
  2. 1secmail  (fallback — no auth needed, but the public API is flaky)

The TempMail interface (create / wait_for_link) stays identical across providers.

Fixes over the previous version:
  - The httpx client is now created lazily and re-created after close(), so a
    creator retry (which calls _cleanup -> close) can keep polling the inbox.
  - mail.tm domains are fetched from the API instead of hardcoding "mail.tm"
    (mail.tm does not issue addresses on its own domain — it 422s).
  - mail.tm returns `html` as a list of fragments and `text` as a string; both
    shapes are flattened before the verification link is extracted.
  - Link extraction is a three-stage fallback: verify/confirm URL, then any
    higgsfield URL, then the first link whose href looks like an auth callback.
"""
import asyncio
import re
import random
import string
from typing import Any, Callable, Awaitable
import httpx

MAILTM_API = "https://api.mail.tm"

SECMAIL_API = "https://www.1secmail.com/api/v1/"
SECMAIL_DOMAINS = ["1secmail.com", "1secmail.net", "1secmail.org", "esiix.com", "wwjmp.com"]

POLL_INTERVAL = 4
POLL_TIMEOUT = 180

# A URL that clearly is an email-verification callback.
VERIFY_LINK_RE = re.compile(
    r'https?://[^\s"\'<>()]+(?:verify|confirm|activate|validate|auth/callback|token=)[^\s"\'<>()]*',
    re.IGNORECASE,
)
# Any link on the Higgsfield domain.
HIGGSFIELD_LINK_RE = re.compile(r'https?://[^\s"\'<>()]*higgsfield[^\s"\'<>()]*', re.IGNORECASE)
# Any link at all — last resort, filtered by keywords afterwards.
ANY_LINK_RE = re.compile(r'https?://[^\s"\'<>()]+', re.IGNORECASE)

_AUTH_HINTS = ("verify", "confirm", "activate", "validate", "callback", "signup", "token")


def _flatten(value: Any) -> str:
    """mail.tm returns `html` as a list of fragments, `text` as a string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_flatten(v) for v in value)
    if isinstance(value, dict):
        return "\n".join(_flatten(v) for v in value.values())
    return str(value)


def extract_link(body: str) -> str | None:
    """Three-stage extraction, most specific first."""
    for pattern in (VERIFY_LINK_RE, HIGGSFIELD_LINK_RE):
        match = pattern.search(body)
        if match:
            return match.group(0)
    for match in ANY_LINK_RE.finditer(body):
        url = match.group(0)
        if any(hint in url.lower() for hint in _AUTH_HINTS):
            return url
    return None


class TempMail:
    """Async temp inbox with polling for a verification link. Multi-provider with fallback."""

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client
        self._owns_client = client is None
        self.login: str = ""
        self.domain: str = ""
        self.provider: str = "mail.tm"
        self._mailtm_token: str | None = None
        self._mailtm_password: str = ""

    # --- client lifecycle ------------------------------------------------

    @property
    def client(self) -> httpx.AsyncClient:
        """Lazily build the client so it survives close() between retries."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30)
            self._owns_client = True
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    @property
    def address(self) -> str:
        return f"{self.login}@{self.domain}"

    # --- provider creation ----------------------------------------------

    async def create(self) -> str:
        """Generate a fresh mailbox. Tries mail.tm first, falls back to 1secmail."""
        errors = []
        for provider in (self._create_mailtm, self._create_1secmail):
            try:
                return await provider()
            except Exception as exc:  # noqa: BLE001 - want the reason for the fallback
                errors.append(f"{provider.__name__}: {exc}")
                await asyncio.sleep(1)
        raise RuntimeError("all temp mail providers failed: " + " | ".join(errors))

    async def _create_mailtm(self) -> str:
        """Create a mail.tm inbox. The domain must be fetched from the API."""
        self.provider = "mail.tm"
        r = await self.client.get(f"{MAILTM_API}/domains")
        r.raise_for_status()
        domains = r.json().get("hydra:member") or []
        if not domains:
            raise RuntimeError("mail.tm returned no domains")
        # Prefer an active domain; fall back to the first one listed.
        active = [d for d in domains if d.get("isActive")]
        self.domain = (active or domains)[0]["domain"]

        self.login = "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
        self._mailtm_password = "".join(random.choices(string.ascii_letters + string.digits, k=18))
        addr = self.address

        r = await self.client.post(
            f"{MAILTM_API}/accounts",
            json={"address": addr, "password": self._mailtm_password},
        )
        r.raise_for_status()

        r = await self.client.post(
            f"{MAILTM_API}/token",
            json={"address": addr, "password": self._mailtm_password},
        )
        r.raise_for_status()
        self._mailtm_token = r.json()["token"]
        return addr

    async def _create_1secmail(self) -> str:
        self.provider = "1secmail"
        self.login = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
        self.domain = random.choice(SECMAIL_DOMAINS)
        return self.address

    # --- provider reads --------------------------------------------------

    async def get_messages(self) -> list[dict]:
        if self.provider == "1secmail":
            r = await self.client.get(
                SECMAIL_API,
                params={"action": "getMessages", "login": self.login, "domain": self.domain},
            )
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, list) else []

        headers = {"Authorization": f"Bearer {self._mailtm_token}"}
        r = await self.client.get(f"{MAILTM_API}/messages", headers=headers)
        r.raise_for_status()
        return r.json().get("hydra:member", [])

    async def read_message(self, msg_id: str) -> str:
        """Return the message body as plain text, normalised across providers."""
        if self.provider == "1secmail":
            r = await self.client.get(
                SECMAIL_API,
                params={
                    "action": "readMessage",
                    "login": self.login,
                    "domain": self.domain,
                    "id": msg_id,
                },
            )
            r.raise_for_status()
            full = r.json()
            return _flatten(
                full.get("htmlBody") or full.get("body") or full.get("textBody") or ""
            )

        headers = {"Authorization": f"Bearer {self._mailtm_token}"}
        r = await self.client.get(f"{MAILTM_API}/messages/{msg_id}", headers=headers)
        r.raise_for_status()
        full = r.json()
        return "\n".join(
            part for part in (_flatten(full.get("html")), _flatten(full.get("text"))) if part
        )

    # --- the bit creator.py calls ---------------------------------------

    async def wait_for_link(
        self,
        log: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        async def _noop(_m: str) -> None:
            pass

        _log = log or _noop
        elapsed = 0
        seen: set[str] = set()
        while elapsed < POLL_TIMEOUT:
            try:
                msgs = await self.get_messages()
            except Exception as exc:  # noqa: BLE001 - transient network / rate limit
                await _log(f"inbox poll error: {exc}")
                await asyncio.sleep(POLL_INTERVAL)
                elapsed += POLL_INTERVAL
                continue

            for m in msgs:
                mid = str(m.get("id"))
                if mid in seen:
                    continue
                seen.add(mid)
                await _log(f"mail from {m.get('from', '?')}: {m.get('subject', '?')}")
                try:
                    body = await self.read_message(mid)
                except Exception as exc:  # noqa: BLE001
                    await _log(f"could not read message {mid}: {exc}")
                    continue
                link = extract_link(body)
                if link:
                    return link

            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL

        raise TimeoutError("no verification mail received within timeout")
