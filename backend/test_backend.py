#!/usr/bin/env python3
"""Self-check for the backend — no network, no browser, no server needed.

    cd backend && python test_backend.py

Exercises the parts that break silently: proxy parsing, proxy rotation,
verification-link extraction, the account lifecycle, and the HTTP API
(including the upload validation path).

The previous stress_test.py was removed — it imported ProxyPool(...) with a
`max_per_ip_per_hour` argument and an `account_cooldown()` helper, neither of
which ever existed in creator.py, so it failed at import.
"""
import asyncio
import os
import sys
import tempfile

# Point every write target at a throwaway directory BEFORE importing main,
# which creates its directories at import time.
os.environ.setdefault("UPLOAD_DIR", tempfile.mkdtemp(prefix="genjutsu-uploads-"))
os.environ.setdefault("VIDEO_DIR", tempfile.mkdtemp(prefix="genjutsu-videos-"))
os.environ.setdefault("DEBUG_DIR", tempfile.mkdtemp(prefix="genjutsu-debug-"))
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(prefix="genjutsu-db-"), "accounts.db"))
os.environ.setdefault("API_KEY", "")  # auth off for the test

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx  # noqa: E402

from creator import BROWSER_ARGS, FingerprintRandomizer, PROXY_POOL  # noqa: E402
from database import (  # noqa: E402
    get_account_with_credits,
    init_db,
    list_accounts,
    mark_banned,
    mark_used,
    save_account,
)
from proxy_manager import ProxyManager, load_proxy_list, parse_proxy_line  # noqa: E402
from temp_mail import TempMail, extract_link  # noqa: E402
import main as backend  # noqa: E402

PASSED = 0
FAILED = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ok   {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name}" + (f" — {detail}" if detail else ""))


async def run() -> bool:
    print("=" * 64)
    print("genjutsu-unlimited — backend self-check")
    print("=" * 64)

    # ---------------------------------------------------------------- 1
    print("\n[1] Container-safe Chromium flags")
    check("--no-sandbox present (Chromium cannot start in Docker without it)",
          "--no-sandbox" in BROWSER_ARGS)
    check("--disable-dev-shm-usage present (/dev/shm is 64 MB in containers)",
          "--disable-dev-shm-usage" in BROWSER_ARGS)
    check("automation flag still present",
          "--disable-blink-features=AutomationControlled" in BROWSER_ARGS)

    # ---------------------------------------------------------------- 2
    print("\n[2] Fingerprint spoofing")
    fp = FingerprintRandomizer()
    script = fp.stealth_script()
    for marker in ("webdriver", "toDataURL", "37445", "createOscillator", "permissions"):
        check(f"stealth script patches {marker}", marker in script)
    check("timezone is a real IANA name", "/" in fp.timezone, fp.timezone)

    # ---------------------------------------------------------------- 3
    print("\n[3] Proxy line parsing")
    check("host:port:user:pass -> socks5h url",
          parse_proxy_line("1.2.3.4:8080:user:pass") == "socks5h://user:pass@1.2.3.4:8080",
          parse_proxy_line("1.2.3.4:8080:user:pass"))
    check("password containing a colon survives",
          parse_proxy_line("1.2.3.4:8080:user:pa:ss") == "socks5h://user:pa:ss@1.2.3.4:8080")
    check("already-formed url passes through",
          parse_proxy_line("socks5h://u:p@h:1") == "socks5h://u:p@h:1")
    check("garbage passes through untouched", parse_proxy_line("nonsense") == "nonsense")

    # ---------------------------------------------------------------- 4
    print("\n[4] Proxy rotation")
    pm = ProxyManager(["socks5h://a:1", "socks5h://b:2", "socks5h://c:3"])
    check("pool size", pm.size == 3)
    first = await pm.next()
    second = await pm.next()
    check("rotation returns different proxies", first != second, f"{first} vs {second}")
    for _ in range(3):
        await pm.record_failure("socks5h://a:1")
    check("a proxy with 3 failures is unhealthy",
          not pm.get_info("socks5h://a:1").is_healthy)
    await pm.reset_failure("socks5h://a:1")
    check("reset_failure restores health",
          pm.get_info("socks5h://a:1").is_healthy)
    status = pm.status()
    check("status hides credentials", "@***" in status["proxies"][0]["url"],
          status["proxies"][0]["url"])
    check("empty pool yields None",
          await ProxyManager([]).next() is None, "expected None for empty pool")

    # ---------------------------------------------------------------- 5
    print("\n[5] Verification-link extraction")
    check("plain verify link",
          extract_link('<a href="https://higgsfield.ai/verify?token=abc">') ==
          "https://higgsfield.ai/verify?token=abc")
    check("higgsfield link without a keyword still matches",
          (extract_link("welcome https://higgsfield.ai/dashboard") or "").startswith(
              "https://higgsfield.ai/"))
    check("keyword-only link as last resort",
          (extract_link("click https://tracker.example/confirm?id=9") or "")
          .startswith("https://tracker.example/confirm"))
    check("no link -> None", extract_link("nothing here") is None)

    # ---------------------------------------------------------------- 6
    print("\n[6] Temp mail client survives close()")
    mail = TempMail()
    await mail.close()
    await mail.close()  # must not raise
    try:
        _ = mail.client
        check("client is re-created after close", True)
    except Exception as exc:  # noqa: BLE001
        check("client is re-created after close", False, str(exc))
    await mail.close()

    # ---------------------------------------------------------------- 7
    print("\n[7] Account lifecycle")
    await init_db()
    await save_account("a1@test.local", "pw", credits=1, proxy="socks5h://p1")
    await save_account("a2@test.local", "pw", credits=1, proxy="socks5h://p2")
    acct = await get_account_with_credits()
    check("first active account returned", acct and acct["email"] == "a1@test.local")
    check("proxy is bound to the account", acct.get("proxy") == "socks5h://p1")
    await mark_used("a1@test.local", 0)
    acct2 = await get_account_with_credits()
    check("spent account is skipped", acct2 and acct2["email"] == "a2@test.local")
    await save_account("a3@test.local", "pw", credits=1, proxy="socks5h://p3")
    await mark_banned("a3@test.local")
    rows = {r["email"]: r for r in await list_accounts()}
    check("banned account has status=banned", rows["a3@test.local"]["status"] == "banned")
    check("banned account is never handed out",
          rows["a3@test.local"]["status"] != "active")

    # ---------------------------------------------------------------- 8
    print("\n[8] HTTP API")
    transport = httpx.ASGITransport(app=backend.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/health")
        check("/health returns 200", r.status_code == 200, str(r.status_code))
        check("/health reports workers", "workers" in r.json())

        r = await c.get("/config")
        check("/config returns 200", r.status_code == 200)
        check("/config reports authRequired=false when API_KEY is empty",
              r.json().get("authRequired") is False)

        r = await c.get("/jobs/nope/stream")
        check("/jobs/<unknown>/stream -> 404", r.status_code == 404, str(r.status_code))

        r = await c.get("/jobs/nope/video")
        check("/jobs/<unknown>/video -> 404", r.status_code == 404, str(r.status_code))

        # A non-video upload must be rejected with a 400, not a 500.
        r = await c.post("/generate", files={"video": ("x.txt", b"hello", "text/plain")},
                         data={"prompt": "", "mode": "motion_transfer"})
        check("/generate rejects a non-video with 400", r.status_code == 400, str(r.status_code))

        # A real-looking video is accepted and queued. No worker runs under
        # ASGITransport, so nothing tries to launch a browser.
        r = await c.post("/generate",
                         files={"video": ("clip.mp4", b"\x00" * 4096, "video/mp4")},
                         data={"prompt": "test", "mode": "motion_transfer"})
        check("/generate accepts a video and returns 200", r.status_code == 200, str(r.status_code))
        job_id = r.json().get("jobId") if r.status_code == 200 else None
        check("response carries a jobId", bool(job_id))

        if job_id:
            check("queued job is tracked", job_id in backend.JOBS)
            src = backend.JOBS[job_id].video_source
            check("uploaded file keeps its .mp4 extension",
                  src is not None and src.suffix == ".mp4",
                  str(src))
            check("job sits in the queue, not running",
                  backend.JOBS[job_id].status == "queued",
                  backend.JOBS[job_id].status)

        r = await c.get("/proxies")
        check("/proxies returns 200", r.status_code == 200)

        r = await c.post("/proxies", json={"proxies": ["9.9.9.9:1080:u:p"]})
        check("POST /proxies accepts a list", r.status_code == 200, str(r.status_code))
        check("POST /proxies returns a count", r.json().get("count") == 1, str(r.json()))

    # ---------------------------------------------------------------- 9
    print("\n[9] Proxy list loading from env")
    os.environ["PROXY_LIST"] = "1.1.1.1:1:u:p,2.2.2.2:2:u:p"
    check("comma-separated env list parses to 2 urls", len(load_proxy_list()) == 2)
    os.environ["PROXY_LIST"] = ""
    check("empty env list yields []", load_proxy_list() == [])

    print("\n" + "=" * 64)
    print(f"RESULT: {PASSED} passed, {FAILED} failed")
    print("=" * 64)
    return FAILED == 0


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(run()) else 1)
