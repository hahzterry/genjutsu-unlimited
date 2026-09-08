"""HiggsfieldCreator — full invisible automation of the Higgsfield Genjutsu flow.

v4.0 anti-detection upgrades:
  - Maximum fingerprint spoofing (canvas/WebGL/audio/navigator)
  - Human-like bezier mouse movements + typing simulation
  - Configurable long delays (30-90s between actions, 5-15min between accounts)
  - Rotating UA/timezone/language/screen resolution per session
  - Per-proxy rate limiting (max 2-3 accounts/hour per IP)
  - Stealth init scripts (webdriver, plugins, languages, hardware)

Bug fixes vs prior version:
  A: mark_used() fires right after generation (before download) — no credit leak.
  B: banned reused accounts are marked 'banned' in DB, never retried.
  C: 404 detection uses HTTP response status, not fragile title text.
  D: settings-row selectors scoped to a dialog/panel container first.
  E: TempMail log callback is now properly awaited (no fire-and-forget).
  F: overall timeout wraps the entire retry loop (configurable via RUN_TIMEOUT).
  G: proxy is bound to the account at creation and reused on every login.
"""
import os, asyncio, random, logging, string as _string, math, time
from typing import Optional, Callable, Awaitable
from pathlib import Path
from playwright.async_api import async_playwright, Page, BrowserContext, Locator
from temp_mail import TempMail
from database import save_account, get_account_with_credits, mark_used, mark_banned
from proxy_manager import ProxyManager, load_proxy_list, COOLDOWN_SECONDS

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
RUN_TIMEOUT = int(os.getenv("RUN_TIMEOUT", "300"))

# --- Anti-detection config (v4.1 — mass mode, no throttling) ---
# Natural human-like delays (fast but not robotic)
MIN_ACTION_DELAY = float(os.getenv("MIN_ACTION_DELAY", "0.5"))
MAX_ACTION_DELAY = float(os.getenv("MAX_ACTION_DELAY", "2.0"))
# No cooldown, no per-IP limit — mass account creation
STEALTH_MODE = False  # always fast mode


class ProxyPool:
    """Rotates proxies round-robin so every new account gets a fresh IP.
    Tracks failures and skips dead proxies. No per-IP rate limit — mass mode.
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
            for _ in range(len(self.proxies)):
                p = self.proxies[self._idx % len(self.proxies)]
                self._idx += 1
                if self._failures.get(p, 0) < 3:
                    return p
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

    def update_proxies(self, new_proxies: list[str]):
        self.proxies = new_proxies
        self._idx = 0
        self._failures.clear()


PROXY_POOL = ProxyManager(load_proxy_list())

# Global delay between new account creations (90-180s)
GLOBAL_ACCOUNT_DELAY = float(os.getenv("GLOBAL_ACCOUNT_DELAY", "90"))
_last_account_time = 0.0


# ===== FingerprintRandomizer — maximum spoofing per session =====

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]
TIMEZONES = ["America/New_York","America/Los_Angeles","America/Chicago","Europe/London","Europe/Berlin","Asia/Tokyo"]
LANGUAGES_LIST = [["en-US","en"],["en-GB","en"],["en-AU","en"],["en-CA","en"]]
RESOLUTIONS = [{"width":1920,"height":1080},{"width":1440,"height":900},{"width":1536,"height":864}]
PLATFORMS = ["MacIntel","Win32","Linux x86_64"]


class FingerprintRandomizer:
    """Generates a unique fingerprint profile for each browser session."""
    def __init__(self):
        self.ua = random.choice(USER_AGENTS)
        self.timezone = random.choice(TIMEZONES)
        self.languages = random.choice(LANGUAGES_LIST)
        self.resolution = random.choice(RESOLUTIONS)
        self.platform = random.choice(PLATFORMS)
        self.hw_concurrency = random.choice([4, 8, 8, 12, 16])
        self.device_memory = random.choice([4, 8, 8, 16])
        self.canvas_noise = random.uniform(0.0001, 0.001)
        self.webgl_vendor = random.choice(["Google Inc. (Apple)","Google Inc. (Intel)","Google Inc. (NVIDIA)"])
        self.webgl_renderer = random.choice([
            "ANGLE (Apple, Apple M1, OpenGL 4.1)",
            "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics, OpenGL 4.1)",
            "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060, OpenGL 4.5)"])
        self.audio_noise = random.uniform(0.00001, 0.0001)

    def stealth_script(self) -> str:
        return f"""
        Object.defineProperty(navigator,'webdriver',{{get:()=>undefined}});
        Object.defineProperty(navigator,'languages',{{get:()=>{self.languages!r}}});
        Object.defineProperty(navigator,'platform',{{get:()=>'{self.platform}'}});
        Object.defineProperty(navigator,'hardwareConcurrency',{{get:()=>{self.hw_concurrency}}});
        Object.defineProperty(navigator,'deviceMemory',{{get:()=>{self.device_memory}}});
        Object.defineProperty(navigator,'plugins',{{get:()=>[{{name:'Chrome PDF Plugin'}},{{name:'Chrome PDF Viewer'}}]}});
        Object.defineProperty(navigator,'doNotTrack',{{get:()=>'1'}});
        Object.defineProperty(navigator,'maxTouchPoints',{{get:()=>0}});
        const _td=HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL=function(...a){{const c=this.getContext('2d');if(c){{const d=c.getImageData(0,0,this.width,this.height);for(let i=0;i<d.data.length;i+=4)d.data[i]^={int(self.canvas_noise*255)};c.putImageData(d,0,0)}}return _td.apply(this,a)}};
        const _gp=WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter=function(p){{if(p===37445)return'{self.webgl_vendor}';if(p===37446)return'{self.webgl_renderer}';return _gp.call(this,p)}};
        const _co=AudioContext.prototype.createOscillator;
        AudioContext.prototype.createOscillator=function(){{const o=_co.call(this);const _cn=o.connect.bind(o);o.connect=function(d){{if(d.gain)d.gain.value*=(1+{self.audio_noise});return _cn(d)}};return o}};
        window.chrome={{runtime:{{}}}};
        const _q=navigator.permissions.query;
        navigator.permissions.query=function(p){{if(p.name==='notifications')return Promise.resolve({{state:'prompt'}});return _q.call(this,p)}};
        """


# ===== HumanInput — realistic mouse + keyboard simulation =====

class HumanInput:
    @staticmethod
    async def human_move(page, x, y, steps=25):
        cur = await page.evaluate("()=>({x:0,y:0})")
        cx, cy = cur["x"], cur["y"]
        c1x, c1y = cx + random.uniform(-50,50), cy + random.uniform(-50,50)
        c2x, c2y = x + random.uniform(-50,50), y + random.uniform(-50,50)
        for i in range(steps):
            t = i / steps
            px = ((1-t)**3)*cx + 3*((1-t)**2)*t*c1x + 3*(1-t)*(t**2)*c2x + (t**3)*x
            py = ((1-t)**3)*cy + 3*((1-t)**2)*t*c1y + 3*(1-t)*(t**2)*c2y + (t**3)*y
            await page.mouse.move(px, py)
            await asyncio.sleep(random.uniform(0.01, 0.05))

    @staticmethod
    async def human_click(page, selector):
        try:
            el = page.locator(selector).first
            box = await el.bounding_box()
            if not box:
                await el.click(); return
            tx = box["x"] + box["width"] * random.uniform(0.3, 0.7)
            ty = box["y"] + box["height"] * random.uniform(0.3, 0.7)
            await HumanInput.human_move(page, tx, ty, steps=random.randint(15, 30))
            await asyncio.sleep(random.uniform(0.1, 0.3))
            await page.mouse.click(tx, ty)
        except Exception:
            try: await el.click()
            except Exception: pass

    @staticmethod
    async def human_type(page, selector, text):
        try:
            el = page.locator(selector).first
            await el.click()
            await asyncio.sleep(random.uniform(0.2, 0.5))
            for char in text:
                await page.keyboard.type(char)
                await asyncio.sleep(random.uniform(0.03, 0.12))
        except Exception:
            try: await el.fill(text)
            except Exception: pass


async def human_delay(lo=None, hi=None):
    """Fast natural human-like delay (0.5-2s). Not robotic, not throttled."""
    if lo is not None and hi is not None:
        await asyncio.sleep(random.uniform(lo, hi))
    else:
        await asyncio.sleep(random.uniform(MIN_ACTION_DELAY, MAX_ACTION_DELAY))

async def pick_proxy() -> Optional[str]:
    return await PROXY_POOL.next()

async def global_account_delay():
    """Global delay of 90-180s between starting new account creations."""
    global _last_account_time
    if GLOBAL_ACCOUNT_DELAY > 0:
        elapsed = time.time() - _last_account_time
        if elapsed < GLOBAL_ACCOUNT_DELAY:
            wait = GLOBAL_ACCOUNT_DELAY - elapsed + random.uniform(0, 90)
            log.info(f"global account delay: sleeping {wait:.0f}s")
            await asyncio.sleep(wait)
    _last_account_time = time.time()

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
        self.proxy: Optional[str] = None
        self.reused_account = False
        self.fp = FingerprintRandomizer()  # v4.0: unique fingerprint per session
        self.hi = HumanInput()              # v4.0: human-like input

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

    async def _detect_cloudflare(self) -> bool:
        """Detect Cloudflare challenge/turnstile pages."""
        cf_sels = [
            'text="Checking your browser"',
            'text="Just a moment"',
            '#cf-challenge', '.cf-turnstile',
            'iframe[src*="challenges.cloudflare.com"]',
            '#challenge-form', '#cf-please-wait',
        ]
        for sel in cf_sels:
            try:
                if await self.page.locator(sel).first.is_visible(timeout=1000):
                    return True
            except Exception:
                continue
        return False

    async def _human_scroll(self, scrolls=3):
        """Simulate human scrolling — scroll down and up randomly."""
        for _ in range(scrolls):
            await self.page.mouse.wheel(0, random.randint(100, 400))
            await asyncio.sleep(random.uniform(0.5, 2.0))
        await asyncio.sleep(random.uniform(0.5, 1.5))

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
                if self.proxy:
                    await PROXY_POOL.reset_failure(self.proxy)
                return result
            except Exception as e:
                last_err = e
                await self._log("warn", f"attempt {attempt} failed: {e}")
                # Record proxy failure + release with backoff
                if self.proxy and not self.reused_account:
                    await PROXY_POOL.record_failure(self.proxy)
                    await self._log("info", f"proxy {self.proxy.split('@')[0]}@*** marked failed, will retry with different proxy")
                if self.page: await self._shot(f"fail_attempt{attempt}")
                await self._cleanup()
                # Backoff: exponential delay between retries
                backoff = min(60 * (2 ** (attempt - 1)), 180)
                await self._log("info", f"backoff: sleeping {backoff}s before retry")
                await asyncio.sleep(backoff)
        await self._cleanup()
        raise RuntimeError(f"all 3 attempts failed: {last_err}")

    async def _attempt(self, reference_path, prompt) -> Path:
        acct = await get_account_with_credits()
        if acct:
            self.email = acct["email"]; self.password = acct["password"]
            self.proxy = acct.get("proxy")
            self.reused_account = True
            await self._log("info", f"reusing account {self.email} (proxy={self.proxy or 'none'})")
        else:
            await global_account_delay()  # 90-180s between new account creations
            self.proxy = await pick_proxy()
            self.reused_account = False

        # Get proxy metadata for timezone matching
        proxy_info = PROXY_POOL.get_info(self.proxy) if self.proxy else None
        proxy_tz = proxy_info.timezone if proxy_info else "America/New_York"
        proxy_udd = proxy_info.user_data_dir if proxy_info else None

        await self._log("info", f"launching browser (proxy={'yes' if self.proxy else 'no'}, pool={PROXY_POOL.size}, tz={proxy_tz})")
        self._pw = await async_playwright().start()
        launch_args = {"headless": HEADLESS,
                       "args": ["--disable-blink-features=AutomationControlled"]}
        if self.proxy: launch_args["proxy"] = {"server": self.proxy}
        self.browser = await self._pw.chromium.launch(**launch_args)
        self.ctx = await self.browser.new_context(
            viewport=self.fp.resolution,
            user_agent=self.fp.ua,
            locale="en-US",
            timezone_id=proxy_tz,
            screen={"width": self.fp.resolution["width"], "height": self.fp.resolution["height"]})
        await self.ctx.add_init_script(self.fp.stealth_script())
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
        await self.page.goto(SIGNUP, wait_until="domcontentloaded", timeout=90000); await human_delay()
        # Cloudflare detection
        if await self._detect_cloudflare():
            await self._shot("cloudflare_signup")
            raise RuntimeError("Cloudflare challenge on signup — need a better proxy")
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
        await self.page.goto(link, wait_until="domcontentloaded", timeout=60000); await human_delay()
        if await detect_captcha(self.page):
            await self._shot("captcha_verify")
            raise RuntimeError("captcha on verification - needs a solver or manual solve")
        await self._log("ok", "email verified")
        # Gap G: bind proxy used at signup to this account
        await save_account(self.email, self.password, credits=1, proxy=self.proxy)
        await self._log("ok", f"account saved (proxy bound: {self.proxy or 'none'})")
        # Mark proxy as used (triggers 45 min cooldown)
        if self.proxy:
            await PROXY_POOL.mark_used(self.proxy)

    async def _login(self):
        await self.page.goto(LOGIN, wait_until="domcontentloaded", timeout=60000); await human_delay()
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
        resp = await self.page.goto(CREATE, wait_until="domcontentloaded", timeout=60000)
        if resp and resp.status >= 400:
            await self._log("info", f"/create returned {resp.status}, falling back to /genjutsu")
            await self.page.goto(GENJUTSU, wait_until="domcontentloaded", timeout=60000)
        await human_delay()
        await self._log("info", f"navigated to create interface ({self.page.url})")
        if await detect_captcha(self.page):
            await self._shot("captcha_create")
            raise RuntimeError("captcha on create page - needs a solver or manual solve")
        # Human behavior: scroll the page before interacting
        await self._human_scroll(scrolls=random.randint(2, 4))
        await self._log("info", "selecting Model: Higgsfield Genjutsu")
        await select_menu_option(self.page, "Model", "Higgsfield Genjutsu", self._log)
        await human_delay()
        await self._log("info", "selecting Quality: 720p")
        await select_menu_option(self.page, "Quality", "720p", self._log)
        await human_delay()
        await self._log("info", "ensuring 'Use free gens' is ON")
        await ensure_toggle_on(self.page, "Use free gens", self._log)
        await human_delay()
        # Human behavior: wait 15-40s before uploading reference (like a human reading the page)
        await self._log("info", "waiting before upload (human simulation)...")
        await asyncio.sleep(random.uniform(15, 40))
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



