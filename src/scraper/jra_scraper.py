"""
JRA公式サイトから出走馬・レース情報を取得する
"""
import re
import json
from datetime import datetime, date
from dataclasses import dataclass, field
from typing import Optional
from .base_scraper import BaseScraper

JRA_BASE = "https://www.jra.go.jp"
RACE_TOP = "https://www.jra.go.jp/keiba/today/"


def _safe_int(s: str) -> int:
    try:
        return int(re.search(r"\d+", s).group())
    except Exception:
        return 0


def _safe_float(s: str) -> float:
    try:
        return float(re.search(r"[\d.]+", s).group())
    except Exception:
        return 0.0


@dataclass
class RaceInfo:
    race_id: str
    venue: str
    race_no: int
    race_name: str
    race_date: str
    distance: int
    surface: str          # 芝 / ダート
    direction: str        # 右 / 左 / 直線
    condition: str        # 良 / 稍重 / 重 / 不良
    weather: str
    grade: str            # G1/G2/G3/OP/L/3勝/2勝/1勝/新馬/未勝利
    num_horses: int
    horses: list = field(default_factory=list)


@dataclass
class HorseEntry:
    horse_no: int         # 馬番
    frame_no: int         # 枠番
    horse_name: str
    horse_id: str         # netkeiba ID
    jockey: str
    trainer: str
    weight_carry: float   # 斤量
    odds: Optional[float] = None
    popularity: Optional[int] = None


class JRAScraper(BaseScraper):
    def get_race_list_for_date(self, target_date: date) -> list[dict]:
        """指定日の全レース一覧を取得（過去日程・当日両対応）"""
        date_str = target_date.strftime("%Y%m%d")
        races = []
        seen = set()

        # まず出馬表URL（当日・翌日用）
        url1 = f"https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={date_str}"
        soup1 = self.get(url1)
        if soup1:
            for a in soup1.find_all("a", href=True):
                href = a.get("href", "")
                m = re.search(r"race_id=(\d+)", href)
                if not m:
                    continue
                if "shutuba.html" not in href and "result.html" not in href:
                    continue
                race_id = m.group(1)
                if race_id not in seen:
                    seen.add(race_id)
                    races.append({"race_id": race_id, "url": href, "label": a.get_text(strip=True)})

        # 過去レース（db.netkeibaのリストページ）
        if not races:
            url2 = f"https://db.netkeiba.com/race/list/{date_str}/"
            soup2 = self.get(url2)
            if soup2:
                for a in soup2.find_all("a", href=True):
                    href = a.get("href", "")
                    m = re.search(r"/race/(\d{12})/", href)
                    if not m:
                        continue
                    race_id = m.group(1)
                    if race_id not in seen:
                        seen.add(race_id)
                        races.append({"race_id": race_id, "url": href, "label": a.get_text(strip=True)})

        return races

    def get_shutuba_table(self, race_id: str) -> Optional[RaceInfo]:
        """出馬表または結果ページからレース情報と出走馬を取得（過去対応）"""
        # 出馬表を試す
        url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
        soup = self.get(url)
        # 出馬表がなければ結果ページにフォールバック
        if not soup or not soup.select("tr.HorseList"):
            url = f"https://db.netkeiba.com/race/{race_id}/"
            soup = self.get(url)
        if not soup:
            return None

        # ---- レース基本情報 ----
        race_name_el = soup.select_one(".RaceName")
        race_name = race_name_el.get_text(strip=True) if race_name_el else "不明"

        data_el = soup.select_one(".RaceData01")
        data_text = data_el.get_text(" ", strip=True) if data_el else ""

        distance, surface, direction, condition, weather = self._parse_race_data(data_text)

        data2_el = soup.select_one(".RaceData02")
        data2_text = data2_el.get_text(" ", strip=True) if data2_el else ""
        venue = self._extract_venue(data2_text, race_id)
        race_no = int(race_id[-2:]) if race_id else 0
        grade = self._extract_grade(race_name, data2_text)

        horses = []
        for row in soup.select("tr.HorseList"):
            entry = self._parse_horse_row(row)
            if entry:
                horses.append(entry)

        return RaceInfo(
            race_id=race_id,
            venue=venue,
            race_no=race_no,
            race_name=race_name,
            race_date=race_id[:8],
            distance=distance,
            surface=surface,
            direction=direction,
            condition=condition,
            weather=weather,
            grade=grade,
            num_horses=len(horses),
            horses=horses,
        )

    # ---- private helpers ----

    def _parse_race_data(self, text: str):
        distance = 1600
        surface = "芝"
        direction = "右"
        condition = "良"
        weather = "晴"

        m = re.search(r"(芝|ダート)\s*(\d+)m", text)
        if m:
            surface = m.group(1)
            distance = int(m.group(2))

        for d in ["右", "左", "直線"]:
            if d in text:
                direction = d
                break

        for c in ["不良", "稍重", "重", "良"]:
            if c in text:
                condition = c
                break

        for w in ["晴", "曇", "雨", "小雨", "雪"]:
            if w in text:
                weather = w
                break

        return distance, surface, direction, condition, weather

    def _extract_venue(self, text: str, race_id: str) -> str:
        from config.settings import JRA_VENUES
        venue_code = race_id[4:6] if len(race_id) >= 6 else "05"
        return JRA_VENUES.get(venue_code, "東京")

    def _extract_grade(self, race_name: str, data2: str) -> str:
        for g in ["G1", "G2", "G3", "GⅠ", "GⅡ", "GⅢ"]:
            if g in race_name or g in data2:
                return g.replace("Ⅰ", "1").replace("Ⅱ", "2").replace("Ⅲ", "3")
        for g in ["Listed", "(L)", "オープン", "OP"]:
            if g in race_name or g in data2:
                return "OP"
        if "3勝" in data2 or "1600万" in data2:
            return "3勝"
        if "2勝" in data2 or "1000万" in data2:
            return "2勝"
        if "1勝" in data2 or "500万" in data2:
            return "1勝"
        if "新馬" in data2:
            return "新馬"
        return "未勝利"

    def _parse_horse_row(self, row) -> Optional[HorseEntry]:
        try:
            cells = row.select("td")
            if len(cells) < 7:
                return None

            # 枠番: Waku セル内のspan.Waku_Num または テキスト
            frame_el = cells[0].select_one("span") or cells[0]
            frame_no = _safe_int(frame_el.get_text(strip=True))

            # 馬番: Umaban セル内のテキスト
            horse_no = _safe_int(cells[1].get_text(strip=True))

            # 馬名リンク
            horse_link = cells[3].select_one("a")
            horse_name = horse_link.get_text(strip=True) if horse_link else cells[3].get_text(strip=True)
            horse_href = horse_link.get("href", "") if horse_link else ""
            m = re.search(r"horse/(\d+)", horse_href)
            horse_id = m.group(1) if m else ""

            # 斤量
            weight_carry = _safe_float(cells[5].get_text(strip=True)) if len(cells) > 5 else 55.0

            # 騎手
            jockey_el = cells[6].select_one("a") if len(cells) > 6 else None
            jockey = jockey_el.get_text(strip=True) if jockey_el else (cells[6].get_text(strip=True) if len(cells) > 6 else "不明")

            # 調教師（美浦/栗東のプレフィックスを除去）
            trainer_raw = cells[7].get_text(strip=True) if len(cells) > 7 else "不明"
            trainer = re.sub(r"^(美浦|栗東)", "", trainer_raw).strip()

            # オッズ抽出（netkeiba shutuba table: 通常 cells[9] 付近 / span.Popular_Num など）
            odds_val = None
            # 1. 専用class
            for sel in ['span.Popular_Num', 'span.Odds_Num', 'td.Odds_Ninki span', 'td.Popular span']:
                el = row.select_one(sel)
                if el:
                    m = re.search(r'(\d+\.\d+)', el.get_text(strip=True))
                    if m:
                        odds_val = float(m.group(1))
                        break
            # 2. fallback: 後方のセルから数値パターン
            if odds_val is None and len(cells) >= 10:
                for idx in [9, 8, 10]:
                    if idx < len(cells):
                        text = cells[idx].get_text(strip=True)
                        m = re.search(r'(\d+\.\d+)', text)
                        if m:
                            v = float(m.group(1))
                            if 1.0 <= v <= 999.9:
                                odds_val = v
                                break

            # 馬番が0なら row id="tr_{no}" から取得
            if horse_no == 0:
                row_id = row.get("id", "")
                horse_no = _safe_int(row_id)

            return HorseEntry(
                horse_no=horse_no,
                frame_no=frame_no,
                horse_name=horse_name,
                horse_id=horse_id,
                jockey=jockey,
                trainer=trainer,
                weight_carry=weight_carry,
                odds=odds_val,
            )
        except Exception as e:
            print(f"[jra] horse row parse error: {e}")
            return None
