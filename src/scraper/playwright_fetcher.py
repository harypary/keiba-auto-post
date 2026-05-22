"""
Playwright を使った確実なフェッチャー。
requests で 403 (Bot 検知) を受けた URL に対し、本物の Chromium ブラウザで
取得を試みる。GitHub Actions IP の DB サイト 403 を回避する切り札。

特徴:
- 1度起動した browser/context を再利用して高速化
- リクエスト間に短いランダム待機（人間らしい挙動）
- ステルス JS（webdriver フラグを削除）
"""
import time
import random
import threading
from typing import Optional
from bs4 import BeautifulSoup

_playwright = None
_browser = None
_context = None
_lock = threading.Lock()

UA_DESKTOP = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['ja-JP', 'ja', 'en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
window.chrome = { runtime: {} };
"""


def _ensure_browser():
    """ブラウザを遅延起動して使い回す"""
    global _playwright, _browser, _context
    if _context is not None:
        return _context
    with _lock:
        if _context is not None:
            return _context
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:
            print(f"[playwright_fetcher] playwright import 失敗: {e}")
            return None
        try:
            _playwright = sync_playwright().start()
            _browser = _playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
            )
            _context = _browser.new_context(
                viewport={"width": 1366, "height": 800},
                user_agent=UA_DESKTOP,
                locale="ja-JP",
                timezone_id="Asia/Tokyo",
                extra_http_headers={
                    "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7",
                },
            )
            _context.add_init_script(STEALTH_JS)
            print("[playwright_fetcher] ブラウザ起動完了")
            return _context
        except Exception as e:
            print(f"[playwright_fetcher] ブラウザ起動失敗: {e}")
            return None


def fetch_html(url: str, timeout_ms: int = 25000, wait_after: float = 1.2) -> Optional[str]:
    """指定URLのHTMLを Chromium で取得"""
    ctx = _ensure_browser()
    if ctx is None:
        return None
    page = None
    try:
        page = ctx.new_page()
        # 短いランダム待機（リクエスト間隔を空ける）
        time.sleep(random.uniform(0.5, 1.5))
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        time.sleep(wait_after)   # JS実行待ち
        html = page.content()
        return html
    except Exception as e:
        print(f"[playwright_fetcher] {url} 失敗: {e}")
        return None
    finally:
        if page is not None:
            try: page.close()
            except Exception: pass


def fetch_soup(url: str) -> Optional[BeautifulSoup]:
    """HTMLをパースした BeautifulSoup を返す"""
    html = fetch_html(url)
    if not html:
        return None
    return BeautifulSoup(html, "lxml")


def close_browser():
    """終了時に呼ぶ（cleanup）"""
    global _playwright, _browser, _context
    with _lock:
        try:
            if _context: _context.close()
        except Exception: pass
        try:
            if _browser: _browser.close()
        except Exception: pass
        try:
            if _playwright: _playwright.stop()
        except Exception: pass
        _context = None
        _browser = None
        _playwright = None


import atexit
atexit.register(close_browser)


if __name__ == "__main__":
    # スタンドアロンテスト
    url = "https://db.netkeiba.com/horse/2019104385/"
    print(f"テスト取得: {url}")
    s = fetch_soup(url)
    if s:
        title = s.find("title")
        print(f"  → 成功: title = {title.text if title else '?'}")
    else:
        print("  → 失敗")
    close_browser()
