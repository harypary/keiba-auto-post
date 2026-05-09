"""
拡張スクレイパー
- 騎手×馬の相性（過去同騎手での成績）
- 調教師×騎手コンビ成績
- netkeiba コラム・競馬ブックのオッズ推移
- 前走タイム比較（コース・距離補正）
- 調教タイム・追い切り評価
"""
import re
import time
from dataclasses import dataclass, field
from typing import Optional
from .base_scraper import BaseScraper

NETKEIBA_DB = "https://db.netkeiba.com"


@dataclass
class JockeyHorseAffinity:
    """騎手×馬の相性データ"""
    horse_id: str
    jockey: str
    total: int
    wins: int
    top3: int
    win_rate: float
    place_rate: float
    avg_order: float


@dataclass
class JockeyStats:
    """騎手の条件別成績"""
    jockey: str
    total: int
    wins: int
    win_rate: float
    place_rate: float
    by_surface: dict = field(default_factory=dict)
    by_venue: dict = field(default_factory=dict)
    by_distance: dict = field(default_factory=dict)


@dataclass
class TrainingInfo:
    """調教情報"""
    horse_id: str
    last_workout_date: str
    workout_type: str       # 坂路/CW/ウッド等
    workout_time: str       # ラップタイム
    workout_comment: str    # 調教師コメント
    condition_rating: str   # A/B/C 評価


class ExtendedScraper(BaseScraper):

    def get_jockey_horse_affinity(self, horse_id: str, jockey: str) -> JockeyHorseAffinity:
        """馬の過去レースから特定騎手との相性を抽出"""
        result_soup = self.get(f"{NETKEIBA_DB}/horse/result/{horse_id}/")
        if not result_soup:
            return JockeyHorseAffinity(horse_id, jockey, 0, 0, 0, 0.0, 0.0, 0.0)

        table = result_soup.select_one("table.db_h_race_results")
        if not table:
            return JockeyHorseAffinity(horse_id, jockey, 0, 0, 0, 0.0, 0.0, 0.0)

        rows_with_jockey = []
        for row in table.find_all("tr")[1:]:
            cells = row.find_all("td")
            if len(cells) < 13:
                continue
            row_jockey = cells[12].get_text(strip=True)
            if jockey in row_jockey or row_jockey in jockey:
                rows_with_jockey.append(cells)

        total = len(rows_with_jockey)
        wins = 0
        top3 = 0
        orders = []
        for cells in rows_with_jockey:
            try:
                order_str = cells[11].get_text(strip=True)
                order = _order_int(order_str)
                if order < 99:
                    orders.append(order)
                if order == 1:
                    wins += 1
                if order <= 3:
                    top3 += 1
            except Exception:
                pass

        avg_order = sum(orders) / len(orders) if orders else 99.0
        return JockeyHorseAffinity(
            horse_id=horse_id, jockey=jockey,
            total=total, wins=wins, top3=top3,
            win_rate=wins/total if total > 0 else 0.0,
            place_rate=top3/total if total > 0 else 0.0,
            avg_order=round(avg_order, 1),
        )

    def get_jockey_recent_stats(self, jockey_name: str) -> JockeyStats:
        """騎手の直近成績（netkeiba騎手DB）"""
        # 騎手検索
        search_soup = self.get(
            f"{NETKEIBA_DB}/jockey/result/recent/",
            params={"jockey_name": jockey_name}
        )
        if not search_soup:
            return JockeyStats(jockey_name, 0, 0, 0.0, 0.0)

        table = search_soup.select_one("table.nk_tb_common")
        if not table:
            return JockeyStats(jockey_name, 0, 0, 0.0, 0.0)

        total = wins = 0
        for row in table.find_all("tr")[1:6]:  # 直近数行
            cells = row.find_all("td")
            if len(cells) < 5:
                continue
            try:
                total += _int(cells[2].get_text(strip=True))
                wins  += _int(cells[3].get_text(strip=True))
            except Exception:
                pass

        place_rate = 0.0
        wr = wins / total if total > 0 else 0.0
        return JockeyStats(
            jockey=jockey_name, total=total, wins=wins,
            win_rate=wr, place_rate=place_rate
        )

    def get_training_info(self, horse_id: str) -> Optional[TrainingInfo]:
        """調教情報を取得（直前追い切り）"""
        soup = self.get(f"https://race.netkeiba.com/horse/training.html?horse_id={horse_id}")
        if not soup:
            return None

        table = soup.select_one("table.TrainingTable")
        if not table:
            return None

        rows = table.find_all("tr")[1:]
        if not rows:
            return None

        try:
            cells = rows[0].find_all("td")
            date_str    = cells[0].get_text(strip=True) if cells else ""
            wtype       = cells[1].get_text(strip=True) if len(cells) > 1 else ""
            wtime       = cells[3].get_text(strip=True) if len(cells) > 3 else ""
            comment     = cells[5].get_text(strip=True) if len(cells) > 5 else ""
            # 追い切り評価（コメントから推定）
            rating = "A" if any(x in comment for x in ["抜群","素晴","仕上","一杯"]) else \
                     "B" if any(x in comment for x in ["良好","普通","まずまず"]) else "C"
            return TrainingInfo(
                horse_id=horse_id,
                last_workout_date=date_str,
                workout_type=wtype,
                workout_time=wtime,
                workout_comment=comment,
                condition_rating=rating,
            )
        except Exception:
            return None

    def get_pace_analysis(self, race_id: str) -> dict:
        """過去の類似コースのペース傾向を取得"""
        # レースIDからコース情報を特定し、過去10レースのペース平均を算出
        venue_code = race_id[4:6]
        distance = race_id  # 簡略化
        return {}   # TODO: 詳細実装


def _order_int(s: str) -> int:
    if any(c in s for c in ["除","取","失","中","降"]):
        return 99
    try:
        return int(re.search(r"\d+", s).group())
    except Exception:
        return 99


def _int(s: str) -> int:
    try:
        return int(re.search(r"\d+", s).group())
    except Exception:
        return 0
