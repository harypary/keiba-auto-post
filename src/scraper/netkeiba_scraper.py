"""
netkeibaから馬の過去成績・適性データを取得する
"""
import re
import json
from dataclasses import dataclass, field
from typing import Optional
from .base_scraper import BaseScraper

NETKEIBA_DB = "https://db.netkeiba.com"


@dataclass
class HorseStats:
    horse_id: str
    horse_name: str
    age: int
    sex: str
    sire: str
    dam: str
    total_races: int
    wins: int
    places: int          # 2着
    shows: int           # 3着
    win_rate: float
    place_rate: float    # 複勝率
    # 条件別成績
    turf_record: dict = field(default_factory=dict)       # 芝
    dirt_record: dict = field(default_factory=dict)       # ダート
    distance_records: dict = field(default_factory=dict)  # 距離帯別
    track_records: dict = field(default_factory=dict)     # 場別
    condition_records: dict = field(default_factory=dict) # 馬場状態別
    recent_results: list = field(default_factory=list)    # 直近5走
    best_distance: Optional[int] = None
    speed_figure: Optional[float] = None   # スピード指数推定


class NetkeibaScraper(BaseScraper):
    def get_horse_stats(self, horse_id: str) -> Optional[HorseStats]:
        """馬の詳細成績を取得"""
        url = f"{NETKEIBA_DB}/horse/{horse_id}/"
        soup = self.get(url)
        if not soup:
            return None

        name_el = soup.select_one(".horse_title h1")
        horse_name = name_el.get_text(strip=True) if name_el else "不明"

        # プロフィール
        profile = self._parse_profile(soup)

        # 通算成績
        total_stats = self._parse_total_stats(soup)

        # 条件別成績
        condition_stats = self._parse_condition_stats(soup)

        # 直近成績
        recent = self._parse_recent_results(soup, max_races=10)

        # スピード指数推定（着差・タイムから算出）
        speed_fig = self._estimate_speed_figure(recent)
        best_dist = self._calc_best_distance(condition_stats.get("distance", {}))

        return HorseStats(
            horse_id=horse_id,
            horse_name=horse_name,
            age=profile.get("age", 0),
            sex=profile.get("sex", "牡"),
            sire=profile.get("sire", ""),
            dam=profile.get("dam", ""),
            total_races=total_stats.get("total", 0),
            wins=total_stats.get("wins", 0),
            places=total_stats.get("places", 0),
            shows=total_stats.get("shows", 0),
            win_rate=total_stats.get("win_rate", 0.0),
            place_rate=total_stats.get("place_rate", 0.0),
            turf_record=condition_stats.get("turf", {}),
            dirt_record=condition_stats.get("dirt", {}),
            distance_records=condition_stats.get("distance", {}),
            track_records=condition_stats.get("track", {}),
            condition_records=condition_stats.get("condition", {}),
            recent_results=recent,
            speed_figure=speed_fig,
            best_distance=best_dist,
        )

    def get_odds(self, race_id: str) -> dict:
        """オッズ取得（発売前・失敗時は空dictで続行）"""
        try:
            resp = self.session.get(
                "https://race.netkeiba.com/api/api_get_odds.html",
                params={"race_id": race_id, "type": "1", "housiki": "c1"},
                timeout=6,
            )
            if resp.status_code == 200:
                data = resp.json()
                odds_map = {}
                for item in data.get("data", {}).get("odds", {}).get("Win", []):
                    try:
                        odds_map[int(item[0])] = float(item[1])
                    except Exception:
                        pass
                return odds_map
        except Exception:
            pass
        return {}  # 発売前または取得失敗→スコアには影響しない

    def get_race_result(self, race_id: str) -> list[dict]:
        """過去レース結果を取得（類似条件分析用）"""
        url = f"https://db.netkeiba.com/race/{race_id}/"
        soup = self.get(url)
        if not soup:
            return []
        results = []
        for row in soup.select("table.race_table_01 tr")[1:]:
            cells = row.select("td")
            if len(cells) < 9:
                continue
            try:
                results.append({
                    "order": cells[0].get_text(strip=True),
                    "horse_no": cells[2].get_text(strip=True),
                    "horse_name": cells[3].get_text(strip=True),
                    "time": cells[7].get_text(strip=True),
                    "margin": cells[8].get_text(strip=True),
                })
            except Exception:
                pass
        return results

    # ---- private helpers ----

    def _parse_profile(self, soup) -> dict:
        profile = {}
        dl = soup.select_one(".db_prof_table")
        if not dl:
            return profile
        rows = dl.select("tr")
        for row in rows:
            th = row.select_one("th")
            td = row.select_one("td")
            if not th or not td:
                continue
            key = th.get_text(strip=True)
            val = td.get_text(strip=True)
            if "生年月日" in key:
                m = re.search(r"(\d{4})", val)
                if m:
                    from datetime import date
                    born_year = int(m.group(1))
                    profile["age"] = date.today().year - born_year
            elif "性齢" in key:
                m = re.match(r"([牡牝セ騸])(\d)", val)
                if m:
                    profile["sex"] = m.group(1)
                    profile["age"] = int(m.group(2))
            elif "父" == key:
                profile["sire"] = val
            elif "母" == key:
                profile["dam"] = val
        return profile

    def _parse_total_stats(self, soup) -> dict:
        stats = {"total": 0, "wins": 0, "places": 0, "shows": 0, "win_rate": 0.0, "place_rate": 0.0}
        table = soup.select_one("table.db_h_sum_table")
        if not table:
            return stats
        rows = table.select("tr")
        for row in rows:
            th = row.select_one("th")
            if not th or "通算" not in th.get_text():
                continue
            cells = row.select("td")
            if len(cells) >= 4:
                try:
                    stats["total"] = int(cells[0].get_text(strip=True) or 0)
                    stats["wins"] = int(cells[1].get_text(strip=True) or 0)
                    stats["places"] = int(cells[2].get_text(strip=True) or 0)
                    stats["shows"] = int(cells[3].get_text(strip=True) or 0)
                    if stats["total"] > 0:
                        stats["win_rate"] = stats["wins"] / stats["total"]
                        place_total = stats["wins"] + stats["places"] + stats["shows"]
                        stats["place_rate"] = place_total / stats["total"]
                except Exception:
                    pass
        return stats

    def _parse_condition_stats(self, soup) -> dict:
        result = {"turf": {}, "dirt": {}, "distance": {}, "track": {}, "condition": {}}
        tables = soup.select("table.db_sum_table")
        for table in tables:
            header = table.select_one("th")
            if not header:
                continue
            label = header.get_text(strip=True)
            rows = table.select("tr")[1:]
            parsed = {}
            for row in rows:
                cells = row.select("td")
                th = row.select_one("th")
                if not th or len(cells) < 4:
                    continue
                key = th.get_text(strip=True)
                try:
                    total = int(cells[0].get_text(strip=True) or 0)
                    wins = int(cells[1].get_text(strip=True) or 0)
                    places = int(cells[2].get_text(strip=True) or 0)
                    shows = int(cells[3].get_text(strip=True) or 0)
                    win_rate = wins / total if total > 0 else 0
                    place_rate = (wins + places + shows) / total if total > 0 else 0
                    parsed[key] = {
                        "total": total, "wins": wins, "places": places, "shows": shows,
                        "win_rate": win_rate, "place_rate": place_rate
                    }
                except Exception:
                    pass
            if "芝・ダート" in label:
                result["turf"] = parsed.get("芝", {})
                result["dirt"] = parsed.get("ダート", {})
            elif "距離" in label:
                result["distance"] = parsed
            elif "競馬場" in label:
                result["track"] = parsed
            elif "馬場状態" in label:
                result["condition"] = parsed
        return result

    def _parse_recent_results(self, soup, max_races: int = 10) -> list[dict]:
        results = []
        table = soup.select_one("table.race_table_01")
        if not table:
            return results
        for row in table.select("tr")[1:max_races+1]:
            cells = row.select("td")
            if len(cells) < 10:
                continue
            try:
                results.append({
                    "date": cells[0].get_text(strip=True),
                    "venue": cells[1].get_text(strip=True),
                    "race_name": cells[4].get_text(strip=True),
                    "order": cells[11].get_text(strip=True),
                    "num_horses": cells[7].get_text(strip=True),
                    "popularity": cells[10].get_text(strip=True),
                    "time": cells[17].get_text(strip=True) if len(cells) > 17 else "",
                    "margin": cells[12].get_text(strip=True) if len(cells) > 12 else "",
                    "jockey": cells[13].get_text(strip=True) if len(cells) > 13 else "",
                    "weight_carry": cells[15].get_text(strip=True) if len(cells) > 15 else "",
                    "distance": cells[14].get_text(strip=True) if len(cells) > 14 else "",
                })
            except Exception:
                pass
        return results

    def _estimate_speed_figure(self, recent: list[dict]) -> float:
        """直近成績からスピード指数を推定（シンプル版）"""
        if not recent:
            return 50.0
        scores = []
        for r in recent[:5]:
            try:
                order = int(r.get("order", "99").replace("中", "99").replace("除", "99").replace("取", "99"))
                num = int(r.get("num_horses", "1") or 1)
                pop = int(r.get("popularity", "99") or 99)
                score = (1 - (order - 1) / max(num - 1, 1)) * 100
                if pop <= 3 and order <= 3:
                    score += 10
                scores.append(score)
            except Exception:
                scores.append(50.0)
        return round(sum(scores) / len(scores), 1) if scores else 50.0

    def _calc_best_distance(self, dist_records: dict) -> Optional[int]:
        """最も勝率が高い距離帯から最適距離を算出"""
        best = None
        best_rate = -1
        for dist_label, rec in dist_records.items():
            rate = rec.get("win_rate", 0)
            total = rec.get("total", 0)
            if total >= 2 and rate > best_rate:
                best_rate = rate
                m = re.search(r"(\d+)", dist_label)
                if m:
                    best = int(m.group(1))
        return best
