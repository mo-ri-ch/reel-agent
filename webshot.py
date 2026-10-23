"""Screenshots of the real news page (mobile size), so a reel can show the actual article scrolling instead of a
drawn card. Uses the Chrome that GitHub's runners already have (no browser download). Never raises: returns None
when the page is blocked, a paywall, a captcha or nearly empty, and the reel uses the drawn source card instead."""
import os
import re

BAD_PAGE = re.compile(r"(?i)captcha|are you a robot|access denied|verify you are human|enable javascript|"
                      r"subscribe to (continue|read)|403 forbidden|page not found|just a moment")
# a terms/privacy/consent page instead of the article or product (23 Oct: editor marked it "irrelevant")
LEGAL_PAGE = re.compile(r"(?i)terms (of|and) (use|service)|privacy (policy|notice|choices)|terms and privacy|"
                        r"before you continue|we value your privacy|cookie (policy|settings)")

HIDE_CLUTTER = """
for (const el of document.querySelectorAll('body *')) {
  const s = getComputedStyle(el);
  if ((s.position === 'fixed' || s.position === 'sticky') && el.offsetHeight < window.innerHeight * 0.9) el.remove();
}
for (const sel of ['[id*=cookie]', '[class*=cookie]', '[id*=consent]', '[class*=consent]', '[class*=newsletter]',
                   '[class*=paywall]', '[id*=onetrust]', 'iframe', '[class*=ad-]', '[id*=ad-]']) {
  document.querySelectorAll(sel).forEach(e => e.remove());
}
document.documentElement.style.overflow = 'auto'; document.body.style.overflow = 'auto';
"""


def _launch(p):
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    extra = {"proxy": {"server": proxy}} if proxy else {}
    for kw in ({"channel": "chrome"}, {}, {"executable_path": "/opt/pw-browsers/chromium/chrome-linux/chrome"}):
        try:
            return p.chromium.launch(headless=True, args=["--no-sandbox"], **kw, **extra)
        except Exception:
            continue
    return None


def capture(url, out_png, screens=2.6, timeout_ms=30000):
    """Mobile screenshot of the top of the page (about `screens` phone screens tall). Returns out_png or None."""
    if not url or not url.startswith("http"):
        return None
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print(f"Web screenshot skipped (no playwright): {e}")
        return None
    try:
        with sync_playwright() as p:
            browser = _launch(p)
            if browser is None:
                print("Web screenshot skipped: no browser")
                return None
            ctx = browser.new_context(ignore_https_errors=bool(os.environ.get("HTTPS_PROXY")), viewport={"width": 412, "height": 915}, device_scale_factor=2.5, is_mobile=True,
                                      has_touch=True, locale="en-US",
                                      user_agent="Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
                                                 "(KHTML, like Gecko) Chrome/129.0 Mobile Safari/537.36")
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            text = page.inner_text("body")[:6000] if page.query_selector("body") else ""
            if len(text) < 600 or BAD_PAGE.search(text[:2500] + " " + (page.title() or "")) or \
                    LEGAL_PAGE.search((page.title() or "") + " " + text[:300]):
                print(f"Web screenshot skipped: blocked or empty page ({len(text)} chars)")
                browser.close()
                return None
            page.evaluate(HIDE_CLUTTER)
            page.wait_for_timeout(400)
            height = min(int(915 * screens), page.evaluate("document.documentElement.scrollHeight"))
            page.screenshot(path=out_png, clip={"x": 0, "y": 0, "width": 412, "height": max(915, height)})
            browser.close()
        return out_png if os.path.exists(out_png) else None
    except Exception as e:
        print(f"Web screenshot failed: {str(e)[:160]}")
        return None


def looks_blank(png):
    """True when the screenshot is almost one colour (a blank or broken page)."""
    try:
        from PIL import Image, ImageStat
        with Image.open(png) as im:
            st = ImageStat.Stat(im.convert("L").resize((60, 140)))
            return st.stddev[0] < 12
    except Exception:
        return True
