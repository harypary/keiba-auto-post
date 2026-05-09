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
        """指定レースの確定着順＋払戻データを取得"""
        for url in [
            f"https://race.netkeiba.com/race/result.html?race_id={race_id}",
            f"https://db.netkeiba.com/race/{race_id}/",
        ]:
            soup = self.get(url)
            if not soup:
                continue
            order = self._parse_order(soup)
            if not order:
                continue
            payouts = self._parse_payouts(soup)
            return {"race_id": race_id, "order": order, "payouts": payouts}
        return None

    def _parse_payouts(self, soup) -> dict:
        """払戻表を解析。{"単勝": 240, "複勝": [120,180], "馬連": 1240, "ワイド": [...], "3連複": 4520, ...}"""
        payouts = {}
        # 払戻テーブル（複数候補のセレクタ）
        tables = soup.select("table.Payout_Detail_Table, table.pay_table_01, dl.payback_block table")
        if not tables:
            return payouts
        for tbl in tables:
            for row in tbl.select("tr"):
                cells = [c.get_text(" ", strip=True) for c in row.select("th,td")]
                if len(cells) < 2:
                    continue
                kind = cells[0].strip()
                # 払戻金額を抽出
                amount_text = " ".join(cells[1:])
                amounts = []
                for m in re.finditer(r"([\d,]+)\s*円?", amount_text):
                    try:
                        amounts.append(int(m.group(1).replace(",", "")))
                    except Exception:
                        pass
                if amounts:
                    if kind in ("単勝", "Win"):                         payouts["単勝"] = amounts[0]
                    elif kind in ("複勝", "Place"):                     payouts["複勝"] = amounts[:3]
                    elif kind in ("枠連",):                              payouts["枠連"] = amounts[0]
                    elif kind in ("馬連", "Quinella"):                   payouts["馬連"] = amounts[0]
                    elif kind in ("ワイド", "Wide", "枠連"):              payouts["ワイド"] = amounts[:3]
                    elif kind in ("馬単", "Exacta"):                     payouts["馬単"] = amounts[0]
                    elif kind in ("3連複", "三連複", "Trio"):             payouts["3連複"] = amounts[0]
                    elif kind in ("3連単", "三連単", "Trifecta"):         payouts["3連単"] = amounts[0]
        return payouts

    def _parse_order(self, soup) -> list:
        return self._extract_order_from_soup(soup)

    def _fetch_result(self, url: str) -> list:
        """[互換用] 古い呼び出しのために残す"""
        soup = self.get(url)
        if not soup:
            return []
        return self._extract_order_from_soup(soup)

    def _extract_order_from_soup(self, soup) -> list:
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
