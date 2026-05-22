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
        global _NETKEIBA_BLOCKED, _NETKEIBA_403_COUNT

        # サーキットブレーカー: netkeiba がブロック中なら即時 None
        is_netkeiba = "netkeiba" in url
        if is_netkeiba and _NETKEIBA_BLOCKED:
            return None

        # 403 が出た時は最大2回までしかリトライしない（同一IPでUA変えても無駄）
        max_attempts = MAX_RETRIES
        for attempt in range(max_attempts):
            try:
                if attempt > 0:
                    self._rotate_ua()
                time.sleep(REQUEST_DELAY + random.uniform(0, 1.5))
                resp = self.session.get(url, params=params, timeout=20)
                resp.raise_for_status()
                resp.encoding = resp.apparent_encoding
                # 成功したら 403 カウンタリセット
                if is_netkeiba:
                    _NETKEIBA_403_COUNT = 0
                return BeautifulSoup(resp.text, "lxml")
            except requests.RequestException as e:
                msg = str(e)
                if "403" in msg:
                    print(f"[scraper] {url} 403 (bot block) attempt {attempt+1}")
                    if is_netkeiba:
                        _NETKEIBA_403_COUNT += 1
                        # 閾値を超えたらブレーカー作動 → 以降は即時諦め
                        if _NETKEIBA_403_COUNT >= _NETKEIBA_403_THRESHOLD:
                            if not _NETKEIBA_BLOCKED:
                                print(f"[scraper] ⚠️ netkeiba ブロック検知（403が{_NETKEIBA_403_COUNT}回連続）→ サーキットブレーカー作動。以降の netkeiba 呼び出しはスキップしてキャッシュにフォールバック")
                            _NETKEIBA_BLOCKED = True
                            return None
                    # 403 では最大2回まで、長く待たない（同IPで時間置いても無駄）
                    if attempt >= 1:
                        return None
                    self._rotate_ua()
                    time.sleep(2)
                else:
                    print(f"[scraper] {url} attempt {attempt+1} failed: {e}")
                    if attempt < max_attempts - 1:
                        time.sleep(2 * (attempt + 1))
                if attempt == max_attempts - 1:
                    return None
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
