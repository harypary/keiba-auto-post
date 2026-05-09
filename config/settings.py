import os
from dotenv import load_dotenv

load_dotenv()

# Claude API
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# note.com credentials
NOTE_EMAIL = os.getenv("NOTE_EMAIL", "")
NOTE_PASSWORD = os.getenv("NOTE_PASSWORD", "")
NOTE_USER_ID = os.getenv("NOTE_USER_ID", "")

# 有料記事価格設定
NOTE_PRICE_PER_RACE = int(os.getenv("NOTE_PRICE_PER_RACE", "300"))   # 1レース単位
NOTE_PRICE_DAY_PACK = int(os.getenv("NOTE_PRICE_DAY_PACK", "1500"))   # 全レースセット

# データキャッシュ
CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "cache")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "output")

# スクレイピング設定
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "2.5"))   # 秒（大きいほどPC負荷低）
MAX_RETRIES = 2

# JRA開催場コード
JRA_VENUES = {
    "01": "札幌", "02": "函館", "03": "福島", "04": "新潟",
    "05": "東京", "06": "中山", "07": "中京", "08": "京都",
    "09": "阪神", "10": "小倉"
}

# 馬場状態
TRACK_CONDITIONS = {
    "良": "firm", "稍重": "good", "重": "yielding", "不良": "soft"
}

# タイムゾーン
TIMEZONE = "Asia/Tokyo"
