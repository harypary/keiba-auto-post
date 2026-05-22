import time
import random
import requests
from bs4 import BeautifulSoup
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from config.settings import REQUEST_DELAY, MAX_RETRIES

# === netkeiba サーキットブレーカー ===
# Bot ブロック (403) が一定回数連続したら諦めて以降は即時 None を返す
# GitHub Actions IP がブロックされる現象に対応
_NETKEIBA_BLOCKED = False
_NETKEIBA_403_COUNT = 0
_NETKEIBA_403_THRESHOLD = 5   # 連続5回 403 でブレーカー作動
_BLOCKED_DOMAINS = set()


def is_netkeiba_blocked() -> bool:
    return _NETKEIBA_BLOCKED


def reset_circuit_breaker():
    """テスト用: ブレーカー状態をリセット"""
    global _NETKEIBA_BLOCKED, _NETKEIBA_403_COUNT, _BLOCKED_DOMAINS
    _NETKEIBA_BLOCKED = False
    _NETKEIBA_403_COUNT = 0
    _BLOCKED_DOMAINS = set()

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36 Edg/127.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
]

HEADERS = {
    "User-Agent": UA_POOL[0],
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}


class BaseScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def _rotate_ua(self):
        self.session.headers["User-Agent"] = random.choice(UA_POOL)

    def get(self, url: str, params: dict = None) -> BeautifulSoup | None:
        """全URL共通の「諦めない」取得。requests失敗→robust多段(playwright/cache/wayback)へ。"""
        global _NETKEIBA_BLOCKED, _NETKEIBA_403_COUNT, _BLOCKED_DOMAINS

        is_db_netkeiba = "db.netkeiba.com" in url
        domain = url.split("/")[2] if "://" in url else ""

        # 既知ブロックドメインは最初から robust 経路
        if is_db_netkeiba and _NETKEIBA_BLOCKED:
            return self._robust_path(url)
        if domain and domain in _BLOCKED_DOMAINS:
            return self._robust_path(url)

        # 第1段: requests を 2 UA で試す（高速）
        for attempt in range(2):
            try:
                if attempt > 0:
                    self._rotate_ua()
                time.sleep(REQUEST_DELAY + random.uniform(0, 1.5))
                resp = self.session.get(url, params=params, timeout=20)
                resp.raise_for_status()
                resp.encoding = resp.apparent_encoding
                if len(resp.text) > 500:
                    if is_db_netkeiba:
                        _NETKEIBA_403_COUNT = 0
                    return BeautifulSoup(resp.text, "lxml")
            except requests.RequestException as e:
                msg = str(e)
                if "403" in msg:
                    if is_db_netkeiba:
                        _NETKEIBA_403_COUNT += 1
                        if _NETKEIBA_403_COUNT >= _NETKEIBA_403_THRESHOLD and not _NETKEIBA_BLOCKED:
                            print(f"[scraper] ⚠️ db.netkeiba ブロック検知 → robust 経路へ切替")
                            _NETKEIBA_BLOCKED = True
                    print(f"[scraper] {url} 403 attempt {attempt+1}")
                else:
                    print(f"[scraper] {url} {msg[:80]} attempt {attempt+1}")
                if attempt < 1:
                    self._rotate_ua()
                    time.sleep(1)

        # 第2段以降: robust 多段（playwright + cache + wayback + backoff）
        print(f"[scraper] {url} → robust経路発動")
        soup = self._robust_path(url)
        if soup is None and domain:
            _BLOCKED_DOMAINS.add(domain)
        return soup

    def _robust_path(self, url: str) -> BeautifulSoup | None:
        """諦めない多段取得（playwright + Google cache + Wayback + リトライ）"""
        try:
            from src.scraper.robust_fetcher import robust_fetch
            return robust_fetch(url, max_total_seconds=120)
        except Exception as e:
            print(f"[scraper] robust 例外: {e}")
            return None

    # 後方互換
    def _fetch_with_playwright(self, url: str) -> BeautifulSoup | None:
        return self._robust_path(url)

    def _fetch_with_playwright(self, url: str) -> BeautifulSoup | None:
        """諦めない多段取得（playwright + Google cache + Wayback + リトライ）"""
        try:
            from src.scraper.robust_fetcher import robust_fetch
            soup = robust_fetch(url, max_total_seconds=90)
            return soup
        except Exception as e:
            print(f"[scraper] robust fetch 失敗: {e}")
            return None

    def get_json(self, url: str, params: dict = None, retries: int = None) -> dict | None:
        max_attempts = retries if retries is not None else MAX_RETRIES
        for attempt in range(max_attempts):
            try:
                time.sleep(REQUEST_DELAY + random.uniform(0, 0.5))
                resp = self.session.get(url, params=params, timeout=10)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                if attempt < max_attempts - 1:
                    time.sleep(2 * (attempt + 1))
                else:
                    return None
        return None
