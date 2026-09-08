"""HiggsfieldCreator — full invisible automation of the Higgsfield Genjutsu flow.

Pipeline per generation:
  1. create temp email (1secmail)
  2. sign up on higgsfield.ai
  3. poll inbox + open verification link in-browser
  4. log in headless
  5. navigate to Genjutsu
  6. upload reference file
  7. fill prompt
  8. trigger generation
  9. wait for completion
 10. download the result video via page.expect_download()

Anti-detection: undetected-playwright, residential proxy rotation, fingerprint
spoofing, random human-like delays (500-2000ms), robust multi-fallback selectors.
"""
import os
import asyncio
import random
import logging
from typing import Optional, Callable, Awaitable
from pathlib import Path

from undetected_playwright.async_api import async_playwright, Page, BrowserContext

from temp_mail import TempMail
from database import save_account, get_account_with_credits, mark_used

log = logging.getLogger("creator")

HIGGS = "https://higgsfield.ai"
SIGNUP = f"{HIGGS}/signup"
LOGIN = f"{HIGGS}/login"
GENJUTSU = f"{HIGGS}/genjutsu"

PROXY_LIST = [p.strip() for p in os.getenv("PROXY_LIST", "").split(",") if p.strip()]
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
LOCALE = os.getenv("BROWSER_LOCALE", "en-US")
VIDEO_DIR = Path(os.getenv("VIDEO_DIR", "./videos"))
VIDEO_DIR.mkdir(parents=True, exist_ok=True)


async def human_delay(lo: float = 0.5, hi: float = 2.0) -> None:
    await asyncio.sleep(random.uniform(lo, hi))


def pick_proxy() -> Optional[str]:
    return random.choice(PROXY_LIST) if PROXY_LIST else None


def random_password() -> str:
    import string as s
    chars = s.ascii_letters + s.digits + "!@#$%"
    return "".join(random.choices(chars, k=16))


# ---------- robust selector helpers ----------
async def click_any(page: Page, selectors: list[str], timeout: int = 15000) -> bool:
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.wait_for(state="visible", timeout=timeout):
                await loc.click()
                return True
        except Exception:
            continue
    return False


async def fill_any(page: Page, value: str, selectors: list[str], timeout: int = 15000) -> bool:
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.wait_for(state="visible", timeout=timeout):
                await loc.fill(value)
                return True
        except Exception:
            continue
    return False


async def wait_any(page: Page, selectors: list[str], timeout: int = 30000) -> bool:
    for sel in selectors:
        try:
            if await page.locator(sel).first.wait_for(state="visible", timeout=timeout):
                return True
        except Exception:
            continue
    return False


class HiggsfieldCreator:
    def __init__(self, log_cb: Callable[[str, str], Awaitable[None]] | None = None):
        self.log_cb = log_cb
        self.mail = TempMail()
        self.email = ""
        self.password = random_password()
        self.ctx: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    async def _log(self, level: str, msg: str) -> None:
        log.info(f"[{level}] {msg}")
        if self.log_cb:
            await self.log_cb(level, msg)

    async def run(self, reference_path: str, prompt: str) -> Path:
        """Full pipeline with 3 retry attempts."""
        last_err: Optional[Exception] = None
        for attempt in range(1, 4):
            try:
                await self._log("info", f"attempt {attempt}/3")
                return await self._attempt(reference_path, prompt)
            except Exception as e:
                last_err = e
                await self._log("warn", f"attempt {attempt} failed: {e}")
                await self._cleanup()
                await asyncio.sleep(3)
        await self._cleanup()
        raise RuntimeError(f"all 3 attempts failed: {last_err}")

    async def _attempt(self, reference_path: str, prompt: str) -> Path:
        proxy = pick_proxy()
        await self._log("info", f"launching browser (proxy={'yes' if proxy else 'no'})")
        self._pw = await async_playwright().start()
        pw = self._pw
        launch_args = {
            "headless": HEADLESS,
            "locale": LOCALE,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if proxy:
            launch_args["proxy"] = {"server": proxy}
        self.browser = await pw.chromium.launch(**launch_args)
        self.ctx = await self.browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"),
            locale=LOCALE,
        )
        await self.ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            "Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']});"
            "Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});"
        )
        self.page = await self.ctx.new_page()

        acct = await get_account_with_credits()
        if acct:
            self.email = acct["email"]
            self.password = acct["password"]
            await self._log("info", f"reusing account {self.email} ({acct['credits']} credits)")
        else:
            await self._create_account()

        await self._login()
        await self._run_genjutsu(reference_path, prompt)
        video = await self._download_result()
        return video

    async def _create_account(self) -> None:
        self.email = await self.mail.create()
        await self._log("info", f"temp inbox ready: {self.email}")

        await self.page.goto(SIGNUP, wait_until="networkidle")
        await human_delay()

        ok = await fill_any(self.page, self.email, [
            'input[type="email"]', 'input[name="email"]',
            'input[placeholder*="mail" i]', 'input[placeholder*="email" i]',
        ])
        if not ok:
            raise RuntimeError("email field not found on signup")
        await human_delay()

        ok = await fill_any(self.page, self.password, [
            'input[type="password"]', 'input[name="password"]',
            'input[placeholder*="password" i]',
        ])
        if not ok:
            raise RuntimeError("password field not found on signup")
        await human_delay()

        ok = await click_any(self.page, [
            'button[type="submit"]',
            'button:has-text("Sign up")', 'button:has-text("Create")',
            'button:has-text("Register")', 'button:has-text("Continue")',
        ])
        if not ok:
            raise RuntimeError("signup submit button not found")
        await self._log("info", "signup form submitted")

        await self._log("info", "waiting for verification email…")
        link = await self.mail.wait_for_link(
            log=lambda m: asyncio.ensure_future(self._log("info", m))
        )
        await self._log("ok", f"verification link: {link}")
        await self.page.goto(link, wait_until="networkidle")
        await human_delay()
        await self._log("ok", "email verified")

        await save_account(self.email, self.password, credits=1)

    async def _login(self) -> None:
        await self.page.goto(LOGIN, wait_until="networkidle")
        await human_delay()
        await fill_any(self.page, self.email, [
            'input[type="email"]', 'input[name="email"]', 'input[placeholder*="email" i]',
        ])
        await human_delay()
        await fill_any(self.page, self.password, [
            'input[type="password"]', 'input[name="password"]',
        ])
        await click_any(self.page, [
            'button[type="submit"]', 'button:has-text("Log in")', 'button:has-text("Sign in")',
        ])
        await self.page.wait_for_load_state("networkidle")
        await self._log("ok", "logged in")

    async def _run_genjutsu(self, reference_path: str, prompt: str) -> None:
        await self.page.goto(GENJUTSU, wait_until="networkidle")
        await human_delay()
        await self._log("info", "navigated to Genjutsu")

        file_input = self.page.locator('input[type="file"]').first
        await file_input.set_input_files(reference_path)
        await self._log("info", "reference uploaded")
        await human_delay(1, 2)

        ok = await fill_any(self.page, prompt, [
            'textarea[name="prompt"]', 'textarea[placeholder*="prompt" i]',
            'textarea[placeholder*="describe" i]', 'textarea',
        ])
        if not ok:
            raise RuntimeError("prompt textarea not found")
        await self._log("info", "prompt filled")
        await human_delay()

        ok = await click_any(self.page, [
            'button:has-text("Generate")', 'button:has-text("Create")',
            'button:has-text("Render")', 'button[type="submit"]',
        ])
        if not ok:
            raise RuntimeError("generate button not found")
        await self._log("ok", "generation triggered")

        await self._log("info", "waiting for generation to complete…")
        done = await wait_any(self.page, [
            'video[src]', 'a[download]', 'button:has-text("Download")', 'button:has-text("Save")',
        ], timeout=300000)
        if not done:
            raise RuntimeError("generation did not complete in time")
        await self._log("ok", "generation complete")

    async def _download_result(self) -> Path:
        out = VIDEO_DIR / f"genjutsu_{random.randint(10000,99999)}.mp4"
        try:
            async with self.page.expect_download(timeout=60000) as dl_info:
                ok = await click_any(self.page, [
                    'a[download]', 'button:has-text("Download")', 'button:has-text("Save video")',
                ])
                if not ok:
                    raise RuntimeError("no download button")
            download = await dl_info.value
            await download.save_as(str(out))
            await self._log("ok", f"video saved: {out.name}")
        except Exception:
            src = await self.page.locator('video').first.get_attribute("src")
            if not src:
                raise RuntimeError("could not locate result video")
            import httpx
            async with httpx.AsyncClient(timeout=120) as c:
                r = await c.get(src if src.startswith("http") else f"{HIGGS}{src}")
                r.raise_for_status()
                out.write_bytes(r.content)
            await self._log("ok", f"video fetched via src: {out.name}")

        await mark_used(self.email, 0)
        return out

    async def _cleanup(self) -> None:
        try:
            if self.ctx: await self.ctx.close()
            if getattr(self, "browser", None): await self.browser.close()
            if getattr(self, "_pw", None): await self._pw.stop()
        except Exception:
            pass
        await self.mail.close()
        self.ctx = self.page = None
        if hasattr(self, "browser"): self.browser = None
        if hasattr(self, "_pw"): self._pw = None
