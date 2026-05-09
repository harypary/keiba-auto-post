"""
レース結果自動取得（レース後にnetkeibaから実際の着順を取得）
"""
import re
import time
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.scraper.base_scraper import BaseScraper


class ResultsFetcher(BaseScraper):
    def get_race_result(self, race_id: str) -> dict | None:
        """指定レースの確定着順を取得（過去・当日両対応）"""
        # まず race.netkeiba.com を試す（当日〜直近）
        order = self._fetch_result(
            f"https://race.netkeiba.com/race/result.html?race_id={race_id}"
        )
        if order:
            return {"race_id": race_id, "order": order}

        # 過去レースは db.netkeiba.com にフォールバック
        order = self._fetch_result(
            f"https://db.netkeiba.com/race/{race_id}/"
        )
        if order:
            return {"race_id": race_id, "order": order}

        return None

    def _fetch_result(self, url: str) -> list:
        soup = self.get(url)
        if not soup:
            return []

        table = (
            soup.select_one("table.RaceTable01")
            or soup.select_one("table.race_table_01")
            or soup.select_one("table.ResultsByRaceDetail")
        )
        if not table:
            return []

        order_list = []
        for row in table.select("tr.HorseList, tr[class*='HorseList']"):
            cells = row.select("td")
            if len(cells) < 5:
                continue
            try:
                order_text = cells[0].get_text(strip=True)
                m = re.search(r"\d+", order_text)
                if not m:
                    continue
                order = int(m.group())
                if order > 20:
                    continue  # 中止・失格は除外

                # 馬番はセル[2]（db.netkeibaでは[1]の場合もある）
                for ci in [2, 1]:
                    if len(cells) > ci:
                        hm = re.search(r"\d+", cells[ci].get_text(strip=True))
                        if hm:
                            horse_no = int(hm.group())
                            break
                else:
                    continue

                horse_link = cells[3].select_one("a") if len(cells) > 3 else None
                horse_name = horse_link.get_text(strip=True) if horse_link else ""

                if horse_no > 0:
                    order_list.append({
                        "order": order,
                        "horse_no": horse_no,
                        "horse_name": horse_name,
                    })
            except Exception:
                continue

        order_list.sort(key=lambda x: x["order"])
        return order_list
