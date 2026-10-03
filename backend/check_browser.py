#!/usr/bin/env python3
"""Verify headless Chromium actually launches with BROWSER_ARGS.

    python check_browser.py

Run this INSIDE the container (Render shell / docker exec) after a deploy.
Chromium refuses to start as root without --no-sandbox, and crashes at random
without --disable-dev-shm-usage, so this is the one thing worth proving on the
real host rather than on a laptop.

Exits 0 on success, 1 on failure.
"""
import asyncio
import sys

from playwright.async_api import async_playwright

from creator import BROWSER_ARGS


async def main() -> int:
    print(f"launching chromium with {len(BROWSER_ARGS)} flags:")
    for arg in BROWSER_ARGS:
        print(f"  {arg}")

    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.launch(headless=True, args=list(BROWSER_ARGS))
    except Exception as exc:
        print(f"\nFAILED to launch chromium: {exc}")
        await pw.stop()
        return 1

    try:
        print(f"\nchromium version: {browser.version}")
        ctx = await browser.new_context(locale="en-US")
        page = await ctx.new_page()

        # Prove the renderer actually executes JS and can paint a page.
        await page.set_content("<h1 id='t'>ok</h1><canvas id='c' width='32' height='32'></canvas>")
        text = await page.inner_text("#t")
        canvas_ok = await page.evaluate(
            "() => { const c = document.getElementById('c'); "
            "return c.getContext('2d') !== null; }"
        )
        print(f"dom text: {text!r}")
        print(f"canvas 2d context: {canvas_ok}")

        if text != "ok" or not canvas_ok:
            print("\nFAILED: renderer did not behave as expected")
            return 1

        print("\nOK: headless chromium launches and renders with these flags")
        return 0
    finally:
        try:
            await browser.close()
        except Exception:
            pass
        await pw.stop()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
