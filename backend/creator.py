"""HiggsfieldCreator — full invisible automation of the Higgsfield Genjutsu flow.

Pipeline: temp email -> signup -> verify -> login -> Create page ->
  Model=Higgsfield Genjutsu, Quality=720p, Use free gens=ON ->
  upload reference -> prompt -> generate -> mark-consumed -> download.

Bug fixes vs prior version:
  A: mark_used() fires right after generation (before download) — no credit leak.
  B: banned reused accounts are marked 'banned' in DB, never retried.
  C: 404 detection uses HTTP response status, not fragile title text.
  D: settings-row selectors scoped to a dialog/panel container first.
  E: TempMail log callback is now properly awaited (no fire-and-forget).
  F: overall 5-minute timeout wraps the entire retry loop.
  G: proxy is bound to the account at creation and reused on every login.
"""
import os, asyncio, random, logging, string as _string
from typing import Optional, Callable, Awaitable
from pathlib import Path
from playwright.async_api import async_playwright, Page, BrowserContext, Locator
from temp_mail import TempMail
from database import save_account, get_account_with_credits, mark_used, mark_banned

log = logging.getLogger("creator")
HIGGS = "https://higgsfield.ai"
SIGNUP = f"{HIGGS}/signup"
LOGIN = f"{HIGGS}/login"
CREATE = f"{HIGGS}/create"
GENJUTSU = f"{HIGGS}/genjutsu"
DEBUG_DIR = Path(os.getenv("DEBUG_DIR", "/tmp/debug")); DEBUG_DIR.mkdir(parents=True, exist_ok=True)
VIDEO_DIR = Path(os.getenv("VIDEO_DIR", "/tmp/videos")); VIDEO_DIR.mkdir(parents=True, exist_ok=True)
PROXY_LIST = [p.strip() for p in os.getenv("PROXY_LIST", "").split(",") if p.strip()]
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
LOCALE = os.getenv("BROWSER_LOCALE", "en-US")
RUN_TIMEOUT = int(os.getenv("RUN_TIMEOUT", "300"))  # Gap F: 5 min overall cap


class ProxyPool:
    """Rotates proxies round-robin so every new account gets a fresh IP.
    Tracks failures and skips dead proxies automatically.
    """
    def __init__(self, proxies: list[str]):
        self.proxies = proxies
        self._idx = 0
        self._failures: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def next(self) -> Optional[str]:
        if not self.proxies:
            return None
        async with self._lock:
            # try up to len(proxies) times to find a healthy one
            for _ in range(len(self.proxies)):
                p = self.proxies[self._idx % len(self.proxies)]
                self._idx += 1
                if self._failures.get(p, 0) < 3:  # skip if 3+ failures
                    return p
            # all proxies are failing — return the least-bad one
            return min(self.proxies, key=lambda p: self._failures.get(p, 0))

    async def record_failure(self, proxy: str):
        async with self._lock:
            self._failures[proxy] = self._failures.get(proxy, 0) + 1

    async def reset(self, proxy: str):
        async with self._lock:
            self._failures.pop(proxy, None)

    @property
    def size(self) -> int:
        return len(self.proxies)


# Singleton proxy pool — shared across all workers
PROXY_POOL = ProxyPool(PROXY_LIST)


async def human_delay(lo=0.5, hi=2.0):
    await asyncio.sleep(random.uniform(lo, hi))

async def pick_proxy() -> Optional[str]:
    """Get the next proxy from the rotating pool (new IP each call)."""
    return await PROXY_POOL.next()

def random_password() -> str:
    return "".join(random.choices(_string.ascii_letters + _string.digits + "!@#$%", k=16))

def random_name() -> tuple[str, str]:
    f = ["Alex","Jordan","Sam","Casey","Riley","Quinn","Avery","Drew"]
    l = ["Carter","Brooks","Reyes","Pierce","Hayes","Cole","Lane","Vega"]
    return random.choice(f), random.choice(l)


async def click_any(scope, selectors, timeout=15000) -> bool:
    for sel in selectors:
        try:
            loc = scope.locator(sel).first
            if await loc.wait_for(state="visible", timeout=timeout):
                await loc.click(); return True
        except Exception:
            continue
    return False

async def fill_any(scope, value, selectors, timeout=15000) -> bool:
    for sel in selectors:
        try:
            loc = scope.locator(sel).first
            if await loc.wait_for(state="visible", timeout=timeout):
                await loc.fill(value); return True
        except Exception:
            continue
    return False

async def wait_any(page, selectors, timeout=30000) -> bool:
    for sel in selectors:
        try:
            if await page.locator(sel).first.wait_for(state="visible", timeout=timeout):
                return True
        except Exception:
            continue
    return False

async def detect_captcha(page) -> bool:
    caps = ['iframe[src*="captcha"]', 'iframe[src*="hcaptcha"]', 'iframe[src*="recaptcha"]',
            'div:has-text("Verify you are human")', '#cf-challenge', '.cf-turnstile', '[data-sitekey]']
    for sel in caps:
        try:
            if await page.locator(sel).first.is_visible(timeout=500):
                return True
        except Exception:
            continue
    return False


async def _find_settings_scope(page) -> Locator:
    """Bug D fix: return the best settings container, or page root as fallback."""
    containers = ['[role="dialog"]', '[aria-modal="true"]', '.settings-panel',
                  '.modal', '[class*="settings" i]', 'main', 'body']
    for c in containers:
        try:
            loc = page.locator(c).first
            if await loc.wait_for(state="visible", timeout=2000):
                return loc
        except Exception:
            continue
    return page


async def select_menu_option(page, row_label, option_text, log_cb=None) -> bool:
    scope = await _find_settings_scope(page)
    row_sels = [f'button:has-text("{row_label}")', f'[role="button"]:has-text("{row_label}")',
                f'div:has-text("{row_label}") >> nth=0', f'text="{row_label}"']
    opened = await click_any(scope, row_sels, timeout=8000)
    if not opened and log_cb: await log_cb("warn", f"could not open '{row_label}' row")
    await human_delay(0.4, 1.0)
    opt_sels = [f'[role="option"]:has-text("{option_text}")', f'li:has-text("{option_text}")',
                f'div[role="menuitem"]:has-text("{option_text}")', f'button:has-text("{option_text}")',
                f'div:has-text("{option_text}") >> nth=0', f'text="{option_text}"']
    picked = await click_any(page, opt_sels, timeout=8000)
    if not picked and log_cb: await log_cb("warn", f"could not pick '{option_text}' from '{row_label}'")
    return picked


async def ensure_toggle_on(page, label_text, log_cb=None) -> bool:
    scope = await _find_settings_scope(page)
    sw_sels = [f'div:has-text("{label_text}") >> [role="switch"]',
               f'div:has-text("{label_text}") >> button[role="switch"]',
               f'div:has-text("{label_text}") >> [aria-checked]',
               f'div:has-text("{label_text}") >> button[type="button"]:has(svg)']
    for sel in sw_sels:
        try:
            sw = scope.locator(sel).first
            if not await sw.wait_for(state="visible", timeout=8000):
                continue
            checked = await sw.get_attribute("aria-checked")
            data_state = await sw.get_attribute("data-state")
            is_on = (checked == "true") or (data_state == "checked")
            if is_on:
                if log_cb: await log_cb("info", f"'{label_text}' already ON")
                return True
            await sw.click(); await human_delay(0.3, 0.8)
            if log_cb: await log_cb("ok", f"'{label_text}' toggled ON")
            return True
        except Exception:
            continue
    if log_cb: await log_cb("warn", f"could not locate toggle '{label_text}'")
    return False


class HiggsfieldCreator:
    def __init__(self, log_cb=None):
        self.log_cb = log_cb
        self.mail = TempMail()
        self.email = ""; self.password = random_password()
        self.first, self.last = random_name()
        self.ctx = None; self.page = None
        self.proxy: Optional[str] = None       # Gap G
        self.reused_account = False             # Bug B

    async def _log(self, level, msg):
        log.info(f"[{level}] {msg}")
        if self.log_cb: await self.log_cb(level, msg)

    async def _shot(self, tag):
        try:
            p = DEBUG_DIR / f"{tag}_{random.randint(1000,9999)}.png"
            await self.page.screenshot(path=str(p), full_page=True)
            await self._log("info", f"debug screenshot: {p}")
        except Exception:
            pass

    async def run(self, reference_path, prompt, image_paths: list[Path] | None = None) -> Path:
        # Gap F: overall timeout wraps the entire retry loop
        self._image_paths = image_paths or []
        try:
            return await asyncio.wait_for(
                self._run_with_retries(reference_path, prompt), timeout=RUN_TIMEOUT
            )
        except asyncio.TimeoutError:
            await self._cleanup()
            raise RuntimeError(f"generation exceeded {RUN_TIMEOUT}s overall timeout")

    async def _run_with_retries(self, reference_path, prompt) -> Path:
        last_err = None
        for attempt in range(1, 4):
            try:
                await self._log("info", f"attempt {attempt}/3")
                result = await self._attempt(reference_path, prompt)
                # Reset proxy failure count on success
                if self.proxy:
                    await PROXY_POOL.reset(self.proxy)
                return result
            except Exception as e:
                last_err = e
                await self._log("warn", f"attempt {attempt} failed: {e}")
                # Record proxy failure so the pool can skip dead proxies
                if self.proxy and not self.reused_account:
                    await PROXY_POOL.record_failure(self.proxy)
                if self.page: await self._shot(f"fail_attempt{attempt}")
                await self._cleanup(); await asyncio.sleep(3)
        await self._cleanup()
        raise RuntimeError(f"all 3 attempts failed: {last_err}")

    async def _attempt(self, reference_path, prompt) -> Path:
        # Gap G + ProxyPool: proxy chosen from rotating pool, bound to account for its lifetime
        acct = await get_account_with_credits()
        if acct:
            self.email = acct["email"]; self.password = acct["password"]
            self.proxy = acct.get("proxy")
            self.reused_account = True
            await self._log("info", f"reusing account {self.email} (proxy={self.proxy or 'none'})")
        else:
            self.proxy = await pick_proxy()  # fresh IP every new account
            self.reused_account = False

        await self._log("info", f"launching browser (proxy={'yes' if self.proxy else 'no'}, pool={PROXY_POOL.size})")
        self._pw = await async_playwright().start()
        launch_args = {"headless": HEADLESS, "locale": LOCALE,
                       "args": ["--disable-blink-features=AutomationControlled"]}
        if self.proxy: launch_args["proxy"] = {"server": self.proxy}
        self.browser = await self._pw.chromium.launch(**launch_args)
        self.ctx = await self.browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
            locale=LOCALE)
        await self.ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            "Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']});"
            "Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});")
        self.page = await self.ctx.new_page()

        if not self.reused_account:
            await self._create_account()
        await self._login()
        await self._run_genjutsu(reference_path, prompt)
        # Bug A fix: mark credit consumed RIGHT AFTER generation succeeds,
        # before the failure-prone download step. No credit leak on download error.
        await mark_used(self.email, 0)
        await self._log("ok", f"account {self.email} marked used (credits=0)")
        return await self._download_result()

    async def _create_account(self):
        self.email = await self.mail.create()
        await self._log("info", f"temp inbox ready: {self.email}")
        await self.page.goto(SIGNUP, wait_until="networkidle"); await human_delay()
        if await detect_captcha(self.page):
            await self._shot("captcha_signup")
            raise RuntimeError("captcha on signup - needs a solver or manual solve")
        await fill_any(self.page, self.first, ['input[name="firstName"]', 'input[name="name"]',
            'input[placeholder*="first name" i]', 'input[placeholder*="name" i]'])
        await fill_any(self.page, self.last, ['input[name="lastName"]', 'input[placeholder*="last name" i]'])
        await human_delay()
        ok = await fill_any(self.page, self.email, ['input[type="email"]', 'input[name="email"]',
            'input[placeholder*="mail" i]', 'input[placeholder*="email" i]'])
        if not ok: raise RuntimeError("email field not found on signup")
        await human_delay()
        ok = await fill_any(self.page, self.password, ['input[type="password"]', 'input[name="password"]',
            'input[placeholder*="password" i]'])
        if not ok: raise RuntimeError("password field not found on signup")
        await human_delay()
        await click_any(self.page, ['input[type="checkbox"]', '[role="checkbox"]'], timeout=3000)
        ok = await click_any(self.page, ['button[type="submit"]', 'button:has-text("Sign up")',
            'button:has-text("Create")', 'button:has-text("Register")', 'button:has-text("Continue")',
            'button:has-text("Get started")'])
        if not ok: raise RuntimeError("signup submit button not found")
        await self._log("info", "signup form submitted")
        await self._log("info", "waiting for verification email...")
        # Bug E fix: async callback, properly awaited inside TempMail.wait_for_link
        link = await self.mail.wait_for_link(log=lambda m: self._log("info", m))
        await self._log("ok", f"verification link: {link}")
        await self.page.goto(link, wait_until="networkidle"); await human_delay()
        if await detect_captcha(self.page):
            await self._shot("captcha_verify")
            raise RuntimeError("captcha on verification - needs a solver or manual solve")
        await self._log("ok", "email verified")
        # Gap G: bind proxy used at signup to this account
        await save_account(self.email, self.password, credits=1, proxy=self.proxy)
        await self._log("ok", f"account saved (proxy bound: {self.proxy or 'none'})")

    async def _login(self):
        await self.page.goto(LOGIN, wait_until="networkidle"); await human_delay()
        if await detect_captcha(self.page):
            await self._shot("captcha_login")
            raise RuntimeError("captcha on login - needs a solver or manual solve")
        await fill_any(self.page, self.email, ['input[type="email"]', 'input[name="email"]',
            'input[placeholder*="email" i]'])
        await human_delay()
        await fill_any(self.page, self.password, ['input[type="password"]', 'input[name="password"]'])
        await click_any(self.page, ['button[type="submit"]', 'button:has-text("Log in")',
            'button:has-text("Sign in")'])
        await self.page.wait_for_load_state("networkidle")
        # Bug B fix: verify login succeeded; mark reused account banned if it failed
        if "/login" in self.page.url:
            if self.reused_account:
                await mark_banned(self.email)
                await self._log("warn", f"account {self.email} marked BANNED (login failed)")
            raise RuntimeError("login failed - still on /login (bad creds or banned)")
        await self._log("ok", "logged in")

    async def _run_genjutsu(self, reference_path, prompt):
        # Bug C fix: use HTTP response status for 404 detection
        resp = await self.page.goto(CREATE, wait_until="networkidle")
        if resp and resp.status >= 400:
            await self._log("info", f"/create returned {resp.status}, falling back to /genjutsu")
            await self.page.goto(GENJUTSU, wait_until="networkidle")
        await human_delay()
        await self._log("info", f"navigated to create interface ({self.page.url})")
        if await detect_captcha(self.page):
            await self._shot("captcha_create")
            raise RuntimeError("captcha on create page - needs a solver or manual solve")
        await click_any(self.page, ['button:has-text("Settings")', '[aria-label*="Settings" i]'], timeout=4000)
        await self._log("info", "selecting Model: Higgsfield Genjutsu")
        await select_menu_option(self.page, "Model", "Higgsfield Genjutsu", self._log)
        await human_delay()
        await self._log("info", "selecting Quality: 720p")
        await select_menu_option(self.page, "Quality", "720p", self._log)
        await human_delay()
        await self._log("info", "ensuring 'Use free gens' is ON")
        await ensure_toggle_on(self.page, "Use free gens", self._log)
        await human_delay()
        # Upload reference VIDEO (required) — find the video file input
        file_inputs = self.page.locator('input[type="file"]')
        count = await file_inputs.count()
        await self._log("info", f"found {count} file input(s) on create page")
        video_uploaded = False
        for i in range(count):
            inp = file_inputs.nth(i)
            accept = await inp.get_attribute("accept") or ""
            if "video" in accept or "video" not in accept:
                try:
                    await inp.set_input_files(reference_path)
                    await self._log("info", f"reference video uploaded to input #{i}")
                    video_uploaded = True
                    break
                except Exception:
                    continue
        if not video_uploaded:
            # fallback: first file input
            await file_inputs.first.set_input_files(reference_path)
            await self._log("info", "reference video uploaded (fallback to first input)")
        await human_delay(1, 2)

        # Upload reference IMAGES (optional, up to 30) — find the image file input
        if self._image_paths:
            img_uploaded = False
            for i in range(count):
                inp = file_inputs.nth(i)
                accept = await inp.get_attribute("accept") or ""
                if "image" in accept:
                    try:
                        await inp.set_input_files([str(p) for p in self._image_paths])
                        await self._log("info", f"{len(self._image_paths)} reference image(s) uploaded to input #{i}")
                        img_uploaded = True
                        break
                    except Exception:
                        continue
            if not img_uploaded and count > 1:
                # try the second input (first was video)
                try:
                    await file_inputs.nth(1).set_input_files([str(p) for p in self._image_paths])
                    await self._log("info", f"{len(self._image_paths)} reference image(s) uploaded (input #1)")
                    img_uploaded = True
                except Exception:
                    pass
            if not img_uploaded:
                await self._log("warn", "could not find a separate image upload input — images may not have been uploaded")
        await human_delay(1, 2)
        ok = await fill_any(self.page, prompt, ['textarea[name="prompt"]',
            'textarea[placeholder*="prompt" i]', 'textarea[placeholder*="describe" i]',
            'textarea[placeholder*="scene" i]', 'textarea'])
        if not ok: raise RuntimeError("prompt textarea not found")
        await self._log("info", "prompt filled")
        await human_delay()
        ok = await click_any(self.page, ['button:has-text("Generate")', 'button:has-text("Create")',
            'button:has-text("Render")', 'button[type="submit"]', 'button:has-text("Make")'])
        if not ok: raise RuntimeError("generate button not found")
        await self._log("ok", "generation triggered")
        await self._log("info", "waiting for generation to complete...")
        done = await wait_any(self.page, ['video[src]', 'a[download]', 'button:has-text("Download")',
            'button:has-text("Save")', 'button:has-text("Download video")'], timeout=300000)
        if not done: raise RuntimeError("generation did not complete in time")
        await self._log("ok", "generation complete")

    async def _download_result(self) -> Path:
        out = VIDEO_DIR / f"genjutsu_{random.randint(10000,99999)}.mp4"
        try:
            async with self.page.expect_download(timeout=60000) as dl_info:
                ok = await click_any(self.page, ['a[download]', 'button:has-text("Download")',
                    'button:has-text("Save video")', 'button:has-text("Download video")'])
                if not ok: raise RuntimeError("no download button")
            download = await dl_info.value
            await download.save_as(str(out))
            await self._log("ok", f"video saved: {out.name}")
        except Exception:
            src = await self.page.locator('video').first.get_attribute("src")
            if not src:
                raise RuntimeError("could not locate result video")
            url = src if src.startswith("http") else f"{HIGGS}{src}"
            resp = await self.page.request.get(url)
            if resp.ok:
                out.write_bytes(await resp.body())
                await self._log("ok", f"video fetched via src: {out.name}")
            else:
                raise RuntimeError(f"video fetch failed: HTTP {resp.status}")
        return out

    async def _cleanup(self):
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



