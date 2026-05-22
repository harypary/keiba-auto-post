"""
諦めない多段フェッチャー。分析に必要なデータは必ず取得する設計。

戦略（順次トライ、成功した時点で返却）:
1. requests (UA ローテーション × 3 試行)
2. playwright (本物 Chromium、ステルス)
3. Google Web Cache (キャッシュ取得)
4. Wayback Machine (アーカイブ)
5. requests に長時間 backoff して再試行 (一時的なブロック対策)
6. playwright を新しいブラウザコンテキストで再試行

全段失敗時のみ None を返すが、レイヤーの厚みで実質ほぼ確実取得。
"""
import time
import random
import urllib.parse
from typing import Optional
from bs4 import BeautifulSoup
import requests


UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36 Edg/127.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
]

BASE_HEADERS = {
    "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "no-cache",
}


def _try_requests(url: str, ua: str, timeout: int = 20) -> Optional[BeautifulSoup]:
    headers = dict(BASE_HEADERS); headers["User-Agent"] = ua
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        if r.status_code == 200 and len(r.text) > 500:
            r.encoding = r.apparent_encoding
            return BeautifulSoup(r.text, "lxml")
    except Exception:
        pass
    return None


def _try_playwright(url: str) -> Optional[BeautifulSoup]:
    try:
        from src.scraper.playwright_fetcher import fetch_soup
        return fetch_soup(url)
    except Exception as e:
        print(f"[robust] playwright失敗: {e}")
        return None


def _try_google_cache(url: str) -> Optional[BeautifulSoup]:
    """Google ウェブキャッシュからの取得（Google が同URLをキャッシュしている場合）"""
    cache_url = f"https://webcache.googleusercontent.com/search?q=cache:{urllib.parse.quote(url, safe='')}"
    soup = _try_requests(cache_url, random.choice(UA_POOL))
    if soup:
        # Google ヘッダ部を除去（ターゲットHTMLの一部のみ取れる場合あり）
        title = soup.find("title")
        if title and "404" not in title.text and "Not Found" not in title.text:
            return soup
    return None


def _try_wayback(url: str) -> Optional[BeautifulSoup]:
    """Wayback Machine から最新スナップショット取得"""
    api_url = f"http://archive.org/wayback/available?url={urllib.parse.quote(url, safe='')}"
    try:
        r = requests.get(api_url, timeout=15)
        if r.status_code == 200:
            data = r.json()
            snap = data.get("archived_snapshots", {}).get("closest", {})
            snap_url = snap.get("url")
            if snap_url:
                soup = _try_requests(snap_url, random.choice(UA_POOL), timeout=25)
                if soup:
                    return soup
    except Exception as e:
        print(f"[robust] wayback失敗: {e}")
    return None


def robust_fetch(url: str, max_total_seconds: int = 90) -> Optional[BeautifulSoup]:
    """諦めない多段取得。最大 max_total_seconds 秒まで試行。"""
    start = time.time()
    layers = [
        # 第1層: requests × 3 UA
        ("requests-UA1", lambda: _try_requests(url, UA_POOL[0])),
        ("requests-UA2", lambda: _try_requests(url, UA_POOL[1])),
        ("requests-UA3-mobile", lambda: _try_requests(url, UA_POOL[6])),
        # 第2層: playwright
        ("playwright", lambda: _try_playwright(url)),
        # 第3層: 3秒 backoff してから requests 再試行
        ("requests-backoff-3s", lambda: (time.sleep(3), _try_requests(url, random.choice(UA_POOL)))[1]),
        # 第4層: Google cache
        ("google-cache", lambda: _try_google_cache(url)),
        # 第5層: 10秒 backoff してから playwright
        ("playwright-backoff-10s", lambda: (time.sleep(10), _try_playwright(url))[1]),
        # 第6層: Wayback
        ("wayback", lambda: _try_wayback(url)),
        # 第7層: 最後のあがき、25秒 backoff + requests
        ("requests-final-25s", lambda: (time.sleep(25), _try_requests(url, random.choice(UA_POOL)))[1]),
    ]

    for layer_name, fetch_fn in layers:
        if time.time() - start > max_total_seconds:
            print(f"[robust] {url} 時間切れ ({max_total_seconds}秒超)")
            break
        try:
            soup = fetch_fn()
            if soup:
                # 内容の最低限の妥当性チェック
                if len(str(soup)) > 1000:
                    elapsed = time.time() - start
                    print(f"[robust] ✓ {url} 取得成功 (layer={layer_name}, {elapsed:.1f}s)")
                    return soup
        except Exception as e:
            print(f"[robust] {layer_name} 例外: {e}")
            continue

    print(f"[robust] ✗ {url} 全層失敗")
    return None


if __name__ == "__main__":
    test_url = "https://db.netkeiba.com/horse/2019104385/"
    print(f"Testing robust fetch: {test_url}")
    s = robust_fetch(test_url)
    if s:
        t = s.find("title")
        print(f"title: {t.text if t else '?'}")
    else:
        print("全層失敗")
