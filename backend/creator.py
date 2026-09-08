"""HiggsfieldCreator — full invisible automation of the Higgsfield Genjutsu flow.

Pipeline: temp email -> signup -> verify -> login -> Create page ->
  Model=Higgsfield Genjutsu, Quality=720p, Use free gens=ON ->
  upload reference -> prompt -> generate -> download.
"""
import os, asyncio, random, logging, string as _string
from typing import Optional, Callable, Awaitable
from pathlib import Path
from playwright.async_api import async_playwright, Page, BrowserContext
from temp_mail import TempMail
from database import save_account, get_account_with_credits, mark_used

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


async def human_delay(lo=0.5, hi=2.0):
    await asyncio.sleep(random.uniform(lo, hi))

def pick_proxy() -> Optional[str]:
    return random.choice(PROXY_LIST) if PROXY_LIST else None

def random_password() -> str:
    return "".join(random.choices(_string.ascii_letters + _string.digits + "!@#$%", k=16))

def random_name() -> tuple[str, str]:
    f = ["Alex","Jordan","Sam","Casey","Riley","Quinn","Avery","Drew"]
    l = ["Carter","Brooks","Reyes","Pierce","Hayes","Cole","Lane","Vega"]
    return random.choice(f), random.choice(l)


async def click_any(page, selectors, timeout=15000):
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.wait_for(state="visible", timeout=timeout):
                await loc.click(); return True
        except Exception:
            continue
    return False

async def fill_any(page, value, selectors, timeout=15000):
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.wait_for(state="visible", timeout=timeout):
                await loc.fill(value); return True
        except Exception:
            continue
    return False

async def wait_any(page, selectors, timeout=30000):
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

async def select_menu_option(page, row_label, option_text, log_cb=None):
    """Open a settings row (Model/Quality) and pick an option by visible text."""
    row_sels = [f'button:has-text("{row_label}")', f'[role="button"]:has-text("{row_label}")',
                f'div:has-text("{row_label}") >> nth=0', f'text="{row_label}"']
    opened = await click_any(page, row_sels, timeout=8000)
    if not opened and log_cb: await log_cb("warn", f"could not open '{row_label}' row")
    await human_delay(0.4, 1.0)
    opt_sels = [f'[role="option"]:has-text("{option_text}")', f'li:has-text("{option_text}")',
                f'div[role="menuitem"]:has-text("{option_text}")', f'button:has-text("{option_text}")',
                f'div:has-text("{option_text}") >> nth=0', f'text="{option_text}"']
    picked = await click_any(page, opt_sels, timeout=8000)
    if not picked and log_cb: await log_cb("warn", f"could not pick '{option_text}' from '{row_label}'")
    return picked

async def ensure_toggle_on(page, label_text, log_cb=None):
    """Ensure a toggle labelled `label_text` is ON. Click only if currently OFF."""
    sw_sels = [f'div:has-text("{label_text}") >> [role="switch"]',
               f'div:has-text("{label_text}") >> button[role="switch"]',
               f'div:has-text("{label_text}") >> [aria-checked]',
               f'div:has-text("{label_text}") >> button[type="button"]:has(svg)']
    for sel in sw_sels:
        try:
            sw = page.locator(sel).first
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

    async def run(self, reference_path, prompt) -> Path:
        last_err = None
        for attempt in range(1, 4):
            try:
                await self._log("info", f"attempt {attempt}/3")
                return await self._attempt(reference_path, prompt)
            except Exception as e:
                last_err = e
                await self._log("warn", f"attempt {attempt} failed: {e}")
                if self.page: await self._shot(f"fail_attempt{attempt}")
                await self._cleanup(); await asyncio.sleep(3)
        await self._cleanup()
        raise RuntimeError(f"all 3 attempts failed: {last_err}")

    async def _attempt(self, reference_path, prompt) -> Path:
        proxy = pick_proxy()
        await self._log("info", f"launching browser (proxy={'yes' if proxy else 'no'})")
        self._pw = await async_playwright().start()
        launch_args = {"headless": HEADLESS, "locale": LOCALE,
                       "args": ["--disable-blink-features=AutomationControlled"]}
        if proxy: launch_args["proxy"] = {"server": proxy}
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

        acct = await get_account_with_credits()
        if acct:
            self.email = acct["email"]; self.password = acct["password"]
            await self._log("info", f"reusing account {self.email} ({acct['credits']} credits)")
        else:
            await self._create_account()
        await self._login()
        await self._run_genjutsu(reference_path, prompt)
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
        link = await self.mail.wait_for_link(log=lambda m: asyncio.ensure_future(self._log("info", m)))
        await self._log("ok", f"verification link: {link}")
        await self.page.goto(link, wait_until="networkidle"); await human_delay()
        if await detect_captcha(self.page):
            await self._shot("captcha_verify")
            raise RuntimeError("captcha on verification - needs a solver or manual solve")
        await self._log("ok", "email verified")
        await save_account(self.email, self.password, credits=1)

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
        await self._log("ok", "logged in")

    async def _run_genjutsu(self, reference_path, prompt):
        await self.page.goto(CREATE, wait_until="networkidle")
        title = await self.page.title()
        if "404" in title or "not found" in title.lower():
            await self._log("info", "/create not found, falling back to /genjutsu")
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
        file_input = self.page.locator('input[type="file"]').first
        try:
            await file_input.wait_for(state="attached", timeout=15000)
        except Exception:
            raise RuntimeError("file input not found on create page")
        await file_input.set_input_files(reference_path)
        await self._log("info", "reference uploaded")
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
        await mark_used(self.email, 0)
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
