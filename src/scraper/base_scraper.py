import time
import random
import requests
from bs4 import BeautifulSoup
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from config.settings import REQUEST_DELAY, MAX_RETRIES

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class BaseScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def get(self, url: str, params: dict = None) -> BeautifulSoup | None:
        for attempt in range(MAX_RETRIES):
            try:
                time.sleep(REQUEST_DELAY + random.uniform(0, 1))
                resp = self.session.get(url, params=params, timeout=15)
                resp.raise_for_status()
                resp.encoding = resp.apparent_encoding
                return BeautifulSoup(resp.text, "lxml")
            except requests.RequestException as e:
                print(f"[scraper] {url} attempt {attempt+1} failed: {e}")
                if attempt == MAX_RETRIES - 1:
                    return None
                time.sleep(3 * (attempt + 1))
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
