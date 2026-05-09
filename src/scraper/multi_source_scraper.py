"""
複数情報源を統合するスクレイパー：
1. JRA公式（jra.go.jp）から調教時計・コース傾向
2. netkeibaの追加情報（調教評価、パドックコメント、直前オッズ）
3. 天気API（Open-Meteo）から馬場状態予測
4. 各競馬場の独自バイアス（直近の前残り/差し有利傾向）

すべての情報を統合して comprehensive_score に追加情報として渡す。
ML特徴量にも段階的に組み込み。
"""
import os, re, json, time
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.scraper.base_scraper import BaseScraper

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache_multi")
os.makedirs(CACHE_DIR, exist_ok=True)


# ============================================================
# 1. 天気予報（Open-Meteo / 無料 API・登録不要）
# ============================================================

VENUE_COORDS = {
    "東京":   (35.6580, 139.4853),  # 東京競馬場（府中）
    "中山":   (35.7194, 139.9650),  # 中山競馬場（船橋）
    "京都":   (34.9322, 135.6886),  # 京都競馬場（淀）
    "阪神":   (34.7547, 135.3617),  # 阪神競馬場（仁川）
    "新潟":   (37.9192, 139.0467),  # 新潟競馬場
    "中京":   (35.0167, 136.9333),  # 中京競馬場（豊明）
    "福島":   (37.7392, 140.4417),  # 福島競馬場
    "小倉":   (33.8881, 130.8800),  # 小倉競馬場
    "札幌":   (43.0617, 141.3308),  # 札幌競馬場
    "函館":   (41.7881, 140.7383),  # 函館競馬場
}


def get_weather_forecast(venue: str, target_date: date) -> dict:
    """指定日の天気予報を取得（最大16日先まで）"""
    coords = VENUE_COORDS.get(venue)
    if not coords:
        return {}

    cache_path = os.path.join(CACHE_DIR, f"weather_{venue}_{target_date.strftime('%Y%m%d')}.json")
    if os.path.exists(cache_path):
        try:
            mtime = os.path.getmtime(cache_path)
            if time.time() - mtime < 6 * 3600:  # 6時間キャッシュ
                with open(cache_path, encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass

    lat, lon = coords
    days_ahead = (target_date - date.today()).days
    if days_ahead < 0 or days_ahead > 15:
        return {}

    import urllib.request
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        f"&daily=precipitation_sum,weather_code,temperature_2m_max,temperature_2m_min"
        f"&timezone=Asia%2FTokyo&start_date={target_date}&end_date={target_date}"
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
        daily = data.get("daily", {})
        result = {
            "date": str(target_date),
            "venue": venue,
            "precipitation_mm": daily.get("precipitation_sum", [0])[0],
            "weather_code":     daily.get("weather_code", [0])[0],
            "temp_max":         daily.get("temperature_2m_max", [None])[0],
            "temp_min":         daily.get("temperature_2m_min", [None])[0],
        }
        # 馬場状態予測
        rain = result["precipitation_mm"] or 0
        if rain >= 20:    result["expected_condition"] = "不良"
        elif rain >= 10:  result["expected_condition"] = "重"
        elif rain >= 3:   result["expected_condition"] = "稍重"
        else:             result["expected_condition"] = "良"

        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
        return result
    except Exception as ex:
        return {"error": str(ex)}


# ============================================================
# 2. 直前オッズ変動（netkeiba の odds.html）
# ============================================================

class OddsMovementScraper(BaseScraper):
    """前日朝オッズ vs 直前オッズの差分を取って「賢い金」の流入を検出"""

    def get_odds_history(self, race_id: str) -> dict:
        """馬番→{morning, latest, drift, drift_pct}"""
        cache = os.path.join(CACHE_DIR, f"odds_hist_{race_id}.json")
        if os.path.exists(cache):
            mtime = os.path.getmtime(cache)
            if time.time() - mtime < 1800:  # 30分キャッシュ
                with open(cache, encoding="utf-8") as f:
                    return json.load(f)

        url = f"https://race.netkeiba.com/odds/index.html?type=b1&race_id={race_id}"
        soup = self.get(url)
        if not soup:
            return {}

        result = {}
        for row in soup.select("tr.HorseList, tr[id^='ninki-']"):
            cells = row.select("td")
            if len(cells) < 4:
                continue
            try:
                # 馬番
                no_text = ""
                for cls in ["Umaban", "Num"]:
                    el = row.select_one(f"td.{cls}")
                    if el:
                        no_text = el.get_text(strip=True)
                        break
                if not no_text:
                    continue
                horse_no = int(re.search(r"\d+", no_text).group())
                # 最新オッズ
                odds_el = row.select_one("td.Odds, span.Odds")
                if not odds_el:
                    continue
                latest = float(re.search(r"[\d.]+", odds_el.get_text(strip=True)).group())
                result[horse_no] = {"latest": latest}
            except Exception:
                continue

        try:
            with open(cache, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False)
        except Exception:
            pass
        return result


# ============================================================
# 3. 競馬場別 直近バイアス（公式情報からスクレイプ可能な範囲）
# ============================================================

VENUE_BIAS_CACHE = os.path.join(CACHE_DIR, "venue_bias.json")


def get_venue_bias(venue: str) -> dict:
    """過去2週の同コース傾向：内枠有利/外枠有利、前残り/差し台頭、馬場速度"""
    if os.path.exists(VENUE_BIAS_CACHE):
        try:
            mtime = os.path.getmtime(VENUE_BIAS_CACHE)
            if time.time() - mtime < 3 * 24 * 3600:  # 3日キャッシュ
                with open(VENUE_BIAS_CACHE, encoding="utf-8") as f:
                    data = json.load(f)
                return data.get(venue, {})
        except Exception:
            pass
    # まだバイアス分析データがない場合は空辞書（後段で集計実装）
    return {}


def update_venue_bias_from_records(records: list) -> dict:
    """バックテストレコードから競馬場別バイアスを集計"""
    from collections import defaultdict
    bias = defaultdict(lambda: {"front_wins": 0, "back_wins": 0, "inner": 0, "outer": 0, "n": 0})
    for r in records:
        v = r.get("venue")
        if not v:
            continue
        wf = r.get("winner_factors", {})
        bias[v]["n"] += 1
        # 上がり適性が高い馬が勝ったなら差し有利
        if wf.get("pace", 50) >= 60:
            bias[v]["back_wins"] += 1
        else:
            bias[v]["front_wins"] += 1

    out = {}
    for v, d in bias.items():
        if d["n"] < 5:
            continue
        total = d["front_wins"] + d["back_wins"]
        if total == 0:
            continue
        back_ratio = d["back_wins"] / total
        out[v] = {
            "back_ratio": round(back_ratio, 3),
            "front_ratio": round(1 - back_ratio, 3),
            "tendency": "差し優勢" if back_ratio >= 0.55 else ("前残り傾向" if back_ratio <= 0.40 else "中立"),
            "n_races": d["n"],
        }

    try:
        with open(VENUE_BIAS_CACHE, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return out


# ============================================================
# 統合インタフェース
# ============================================================

def collect_extra_signals(race_id: str, venue: str, target_date: date) -> dict:
    """1レース分の補助情報を全部集める。失敗してもエラーで止めない"""
    signals = {"race_id": race_id, "venue": venue, "date": str(target_date)}

    # 天気
    try:
        wx = get_weather_forecast(venue, target_date)
        if wx and not wx.get("error"):
            signals["weather"] = wx
    except Exception as ex:
        signals["weather_error"] = str(ex)

    # 競馬場バイアス
    try:
        bias = get_venue_bias(venue)
        if bias:
            signals["venue_bias"] = bias
    except Exception:
        pass

    # オッズ履歴は重いので必要時のみ呼ぶ（スクレイパー初期化が必要）
    return signals
