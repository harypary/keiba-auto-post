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
    """playwright を使った取得。note 投稿の playwright と競合するため fast モードでは無効化"""
    import os as _os
    # 投稿用 playwright との衝突を避けるため fast モードでは無効
    if _os.environ.get("SCRAPE_MODE", "full").lower() == "fast":
        return None
    # 投稿が始まっているプロセスでも playwright_fetcher を起動すると衝突するので環境変数チェック
    if _os.environ.get("DISABLE_PLAYWRIGHT_FETCH"):
        return None
    try:
        from src.scraper.playwright_fetcher import fetch_soup
        return fetch_soup(url)
    except Exception as e:
        print(f"[robust] playwright失敗: {e}")
        return None


def _strip_google_cache_wrapper(soup: BeautifulSoup) -> BeautifulSoup:
    """Google Cacheの外部フレームを除去し、オリジナルHTMLのみを抽出"""
    try:
        # Google が付与する cache header / footer div を削除
        for tag_id in ("bN015htcoyT__google-cache-hdr", "ghead"):
            el = soup.find(id=tag_id)
            if el: el.decompose()
        # Google が cache header の後に挿入する <div> も除去
        for div in soup.find_all("div", style=lambda x: x and "background" in (x or "")):
            try: div.decompose()
            except Exception: pass
        # iframe / google-related script 削除
        for tag in soup.find_all(["iframe", "script"]):
            try:
                src = tag.get("src", "") or tag.get("href", "")
                if "google" in src.lower():
                    tag.decompose()
            except Exception: pass
    except Exception:
        pass
    return soup


def _strip_wayback_wrapper(soup: BeautifulSoup) -> BeautifulSoup:
    """Wayback Machine のツールバーや wm-* class を除去"""
    try:
        for div_id in ("wm-ipp", "wm-ipp-base", "wm-ipp-print", "donato"):
            el = soup.find(id=div_id)
            if el: el.decompose()
        for cls in ("wb_iframe_wrap", "wm-ipp"):
            for el in soup.find_all(class_=cls):
                try: el.decompose()
                except Exception: pass
        # script で wayback の埋め込み JS を除去
        for s in soup.find_all("script"):
            try:
                src = s.get("src", "") or ""
                if "archive.org" in src or "wayback" in src.lower():
                    s.decompose()
            except Exception: pass
    except Exception:
        pass
    return soup


def _is_valid_netkeiba_horse_page(soup: BeautifulSoup) -> bool:
    """馬個別ページとして有効な構造を持つか判定"""
    if not soup: return False
    # 馬名タイトル / 成績表 / プロフィールテーブルのいずれかが必要
    if soup.select_one(".horse_title h1"): return True
    if soup.select_one("table.db_h_race_results, table.db_prof_table"): return True
    # 馬名と思しき h1 がある場合も許可
    h1 = soup.find("h1")
    if h1 and len(h1.get_text(strip=True)) > 0 and len(h1.get_text(strip=True)) < 30:
        return True
    return False


def _try_google_cache(url: str) -> Optional[BeautifulSoup]:
    """Google ウェブキャッシュからの取得＋フレーム除去"""
    cache_url = f"https://webcache.googleusercontent.com/search?q=cache:{urllib.parse.quote(url, safe='')}"
    soup = _try_requests(cache_url, random.choice(UA_POOL))
    if soup:
        soup = _strip_google_cache_wrapper(soup)
        title = soup.find("title")
        if title and "404" in title.text:
            return None
        # netkeiba 馬ページの構造を持っているか確認
        if "netkeiba" in url and "horse" in url:
            if not _is_valid_netkeiba_horse_page(soup):
                return None
        return soup
    return None


def _try_wayback(url: str) -> Optional[BeautifulSoup]:
    """Wayback Machine から最新スナップショット取得＋ツールバー除去"""
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
                    soup = _strip_wayback_wrapper(soup)
                    if "netkeiba" in url and "horse" in url:
                        if not _is_valid_netkeiba_horse_page(soup):
                            return None
                if soup:
                    return soup
    except Exception as e:
        print(f"[robust] wayback失敗: {e}")
    return None


def robust_fetch(url: str, max_total_seconds: int = 25) -> Optional[BeautifulSoup]:
    """多段取得。max_total_seconds で打ち切り（既定25秒）。
    SCRAPE_MODE=fast の場合は Wayback/Google Cache のような遅い層を省く。
    """
    import os as _os
    fast_mode = _os.environ.get("SCRAPE_MODE", "full").lower() == "fast"
    start = time.time()
    if fast_mode:
        # 高速モード: 早く諦める。requests 2UA + playwright 1回のみ
        layers = [
            ("requests-UA1", lambda: _try_requests(url, UA_POOL[0])),
            ("requests-UA2-mobile", lambda: _try_requests(url, UA_POOL[6])),
            ("playwright", lambda: _try_playwright(url)),
        ]
    else:
        layers = [
            ("requests-UA1", lambda: _try_requests(url, UA_POOL[0])),
            ("requests-UA2", lambda: _try_requests(url, UA_POOL[1])),
            ("requests-UA3-mobile", lambda: _try_requests(url, UA_POOL[6])),
            ("playwright", lambda: _try_playwright(url)),
            ("requests-backoff-3s", lambda: (time.sleep(3), _try_requests(url, random.choice(UA_POOL)))[1]),
            ("google-cache", lambda: _try_google_cache(url)),
            ("playwright-backoff-10s", lambda: (time.sleep(10), _try_playwright(url))[1]),
            ("wayback", lambda: _try_wayback(url)),
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
