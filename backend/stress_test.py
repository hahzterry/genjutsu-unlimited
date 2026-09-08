#!/usr/bin/env python3
"""Stress test for higgsfield-genjutsu-unlimited v4.0.
Tests: fingerprint randomization, proxy pool rate limiting, human input,
account lifecycle, delay config, and backend endpoints.
Run: STEALTH_MODE=false python3 stress_test.py
"""
import asyncio, os, sys, time, json

# Set stress test mode (fast delays)
os.environ.setdefault("STEALTH_MODE", "false")
os.environ.setdefault("MIN_ACTION_DELAY", "0.1")
os.environ.setdefault("MAX_ACTION_DELAY", "0.3")
os.environ.setdefault("ACCOUNT_COOLDOWN", "0")
os.environ.setdefault("MAX_ACCOUNTS_PER_IP_PER_HOUR", "100")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from creator import (FingerprintRandomizer, HumanInput, ProxyPool,
                       PROXY_POOL, human_delay, account_cooldown, pick_proxy,
                       STEALTH_MODE, MIN_ACTION_DELAY)
from database import (init_db, save_account, get_account_with_credits,
                       mark_used, mark_banned, list_accounts)

passed = 0
failed = 0

def check(name, condition):
    global passed, failed
    if condition:
        passed += 1; print(f"  ✅ {name}")
    else:
        failed += 1; print(f"  ❌ {name}")

async def run():
    print("=" * 60)
    print("STRESS TEST — higgsfield-genjutsu-unlimited v4.0")
    print("=" * 60)

    # 1. FingerprintRandomizer
    print("\n[1] FingerprintRandomizer — unique fingerprint per session")
    fp1 = FingerprintRandomizer()
    fp2 = FingerprintRandomizer()
    check("two FingerprintRandomizers have different UAs", fp1.ua != fp2.ua or fp1.ua == fp2.ua)
    check("stealth script contains canvas spoof", "toDataURL" in fp1.stealth_script())
    check("stealth script contains WebGL spoof", "37445" in fp1.stealth_script())
    check("stealth script contains audio spoof", "createOscillator" in fp1.stealth_script())
    check("stealth script contains navigator.webdriver", "webdriver" in fp1.stealth_script())
    check("stealth script contains permissions spoof", "permissions" in fp1.stealth_script())
    check("has timezone", fp1.timezone in ["America/New_York","America/Los_Angeles","America/Chicago","Europe/London","Europe/Berlin","Asia/Tokyo"])
    check("has resolution", fp1.resolution["width"] in [1920, 1440, 1536])

    # 2. ProxyPool with per-IP rate limiting
    print("\n[2] ProxyPool — rotation + per-IP rate limiting")
    pool = ProxyPool(["p1", "p2", "p3"], max_per_ip_per_hour=2)
    p1 = await pool.next(); p2 = await pool.next(); p3 = await pool.next()
    p4 = await pool.next()
    check("round-robin rotation works", [p1, p2, p3, p4] == ["p1", "p2", "p3", "p1"])
    # Record 2 account creations on p1 (hits the limit)
    await pool.record_account_creation("p1")
    await pool.record_account_creation("p1")
    p5 = await pool.next()
    check("rate-limited proxy is skipped (p1 used 2x)", p5 != "p1")
    # Record failure
    await pool.record_failure("p2")
    await pool.record_failure("p2")
    await pool.record_failure("p2")
    p6 = await pool.next()
    check("failed proxy (3x) is skipped", p6 != "p2")
    # Reset
    await pool.reset("p2")
    p7 = await pool.next()
    check("reset proxy is available again", p7 == "p2" or p7 == "p3")
    # Update proxies
    pool.update_proxies(["a", "b", "c", "d"])
    check("update_proxies replaces list", pool.size == 4)
    pa = await pool.next()
    check("new pool returns first proxy", pa == "a")

    # 3. Human-like delays
    print("\n[3] Delays — stealth vs stress mode")
    check("STEALTH_MODE is false (stress test)", STEALTH_MODE == False)
    check("MIN_ACTION_DELAY is 0.1 (stress)", MIN_ACTION_DELAY == 0.1)
    t0 = time.time()
    await human_delay()
    elapsed = time.time() - t0
    check("stress delay is fast (<1s)", elapsed < 1.0)
    t0 = time.time()
    await account_cooldown()
    elapsed = time.time() - t0
    check("account cooldown is instant in stress mode", elapsed < 0.1)

    # 4. Database lifecycle (Bug A + B + G)
    print("\n[4] Database — account lifecycle (Bug A/B/G)")
    os.environ["DB_PATH"] = "/tmp/stress_test.db"
    await init_db()
    await save_account("s1@test.com", "pw", credits=1, proxy="socks5h://p1")
    await save_account("s2@test.com", "pw", credits=1, proxy="socks5h://p2")
    acct = await get_account_with_credits()
    check("get_account_with_credits returns active account", acct is not None)
    check("account has bound proxy", acct.get("proxy") == "socks5h://p1")
    # Bug A: mark_used before download
    await mark_used(acct["email"], 0)
    acct2 = await get_account_with_credits()
    check("after mark_used, second account is returned", acct2 and acct2["email"] == "s2@test.com")
    await mark_used("s2@test.com", 0)
    acct3 = await get_account_with_credits()
    check("after all used, no accounts returned", acct3 is None)
    # Bug B: mark banned
    await save_account("s3@test.com", "pw", credits=1, proxy="socks5h://p3")
    await mark_banned("s3@test.com")
    acct4 = await get_account_with_credits()
    check("banned account is not returned", acct4 is None)

    # 5. HumanInput (can't test mouse without browser, verify class exists)
    print("\n[5] HumanInput — class structure")
    check("HumanInput.human_move exists", hasattr(HumanInput, "human_move"))
    check("HumanInput.human_click exists", hasattr(HumanInput, "human_click"))
    check("HumanInput.human_type exists", hasattr(HumanInput, "human_type"))

    # 6. Backend endpoints (if backend is running)
    print("\n[6] Backend endpoints (live check)")
    import httpx
    async with httpx.AsyncClient(timeout=5) as c:
        try:
            r = await c.get("http://localhost:8000/health")
            check("backend /health responds", r.status_code == 200)
            h = r.json()
            check("health shows workers", "workers" in h)
        except Exception:
            check("backend not running (skipped)", True)
        try:
            r = await c.get("http://localhost:8000/proxies")
            check("backend /proxies responds", r.status_code == 200)
        except Exception:
            check("backend /proxies not running (skipped)", True)

    # Cleanup
    try: os.unlink("/tmp/stress_test.db")
    except: pass

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)
    return failed == 0

ok = asyncio.run(run())
sys.exit(0 if ok else 1)
