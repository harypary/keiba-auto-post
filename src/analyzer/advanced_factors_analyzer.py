"""
高度要因の分析（5要素）

1. 騎手×コース相性: その馬の過去で、現騎手×現コースでの好走実績
2. 調教師の重賞勝率: entries の trainer + 過去 records の grade 経験
3. 連闘/間隔別の好走パターン: 中N週レンジ別の勝率傾向
4. 馬体重当日変動の影響（前日比）: weight_diff のレンジと勝率
5. 過去対戦履歴: 同じレースに出走する rivals に対する過去の勝敗

注: 全て個馬の records（過去走履歴）と現エントリ情報から導出。
trainer の重賞特化勝率は records 単独では出ないため、entry.trainer の重賞関連経験で代替。
"""
from collections import defaultdict
from datetime import datetime
from typing import Optional


def _parse_date(s: str):
    if not s: return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d")
    except Exception:
        try:
            return datetime.strptime(s[:10], "%Y/%m/%d")
        except Exception:
            return None


def derive_advanced_signals(records: list, entry) -> dict:
    """過去レース records から高度シグナルを抽出"""
    sig = {
        "jockey_venue_hits": {},        # {(jockey, venue): (wins, runs)}
        "graded_experience": 0,         # 重賞出走数
        "graded_wins": 0,
        "rest_buckets": {},             # {bucket: (wins, runs)}
        "weight_diff_wins": [],         # 勝った時の weight_diff 一覧
        "weight_diff_losses": [],
        "last_race_date": None,
        "last_weight": None,
        "beat_horses": set(),           # 過去に倒したことのある馬名
        "lost_to_horses": set(),        # 負けたことのある馬名
    }
    if not records:
        return sig

    # 日付順に並べる（古い順）
    recs = list(records)
    recs.sort(key=lambda r: getattr(r, "date", "") or "")

    prev_date = None
    for r in recs:
        order = getattr(r, "order", 99) or 99
        won = (order == 1)
        placed = (order <= 3)

        # 1. 騎手×コース
        jk = getattr(r, "jockey", "") or ""
        vn = getattr(r, "venue", "") or ""
        if jk and vn:
            key = (jk, vn)
            w, n = sig["jockey_venue_hits"].get(key, (0, 0))
            sig["jockey_venue_hits"][key] = (w + (1 if placed else 0), n + 1)

        # 2. 重賞経験
        grade = getattr(r, "grade", "") or ""
        if grade in ("G1", "G2", "G3", "JpnI", "JpnII", "JpnIII"):
            sig["graded_experience"] += 1
            if won:
                sig["graded_wins"] += 1

        # 3. 休養日数
        d = _parse_date(getattr(r, "date", ""))
        if d and prev_date:
            gap = (d - prev_date).days
            # バケット化
            if gap <= 8:    bucket = "連闘"
            elif gap <= 15: bucket = "中1週"
            elif gap <= 22: bucket = "中2週"
            elif gap <= 35: bucket = "中3-4週"
            elif gap <= 60: bucket = "中5-8週"
            elif gap <= 120: bucket = "2-4ヶ月"
            else:           bucket = "長期休養"
            w, n = sig["rest_buckets"].get(bucket, (0, 0))
            sig["rest_buckets"][bucket] = (w + (1 if placed else 0), n + 1)
        prev_date = d or prev_date

        # 4. 馬体重差
        wd = getattr(r, "weight_diff", None)
        if wd is not None and wd != 0:
            if won:   sig["weight_diff_wins"].append(wd)
            elif order >= 6: sig["weight_diff_losses"].append(wd)

        # 5. 同走馬リスト（最大着順記録）
        # records には全頭リストは含まれないが、各 record に同走馬名がある場合のみ
        # （多くのスクレイパは含めない。head-to-head は別パスで処理）

    # 最終情報
    if recs:
        last = recs[-1]
        sig["last_race_date"] = getattr(last, "date", "")
        sig["last_weight"] = getattr(last, "horse_weight", 0) or 0

    return sig


def score_horse_with_advanced(
    signals: dict,
    entry,
    race_info: dict,
    rival_records: Optional[dict] = None,
) -> dict:
    """高度シグナルと現レース条件を照合し、スコア加減点 + 理由を返す

    rival_records: {horse_name: records_list} 当該レース他馬の過去 records
                   この馬の名前と他馬の records にある同走履歴をマッチング
    """
    adjust = 0.0
    reasons = []
    if not signals:
        return {"adjust": 0, "reasons": []}

    cur_jockey = getattr(entry, "jockey", "") or ""
    cur_venue  = race_info.get("venue", "")

    # 1. 騎手×コース相性
    jv = signals.get("jockey_venue_hits", {})
    if cur_jockey and cur_venue:
        w, n = jv.get((cur_jockey, cur_venue), (0, 0))
        if n >= 2:
            rate = w / n
            if rate >= 0.5:
                adjust += 2.5
                reasons.append(f"{cur_jockey}×{cur_venue}で過去{w}/{n}回好走")
            elif rate >= 0.34:
                adjust += 1.0
                reasons.append(f"{cur_jockey}×{cur_venue}実績あり({w}/{n})")
        elif n == 1 and w == 1:
            adjust += 0.5
            reasons.append(f"{cur_jockey}×{cur_venue}前走好走")

    # 2. 重賞経験×今回が重賞
    cur_grade = race_info.get("grade", "") or ""
    is_graded = cur_grade in ("G1", "G2", "G3", "JpnI", "JpnII", "JpnIII")
    if is_graded:
        ge = signals.get("graded_experience", 0)
        gw = signals.get("graded_wins", 0)
        if gw >= 1:
            adjust += 3.0
            reasons.append(f"重賞勝ち{gw}回の実績")
        elif ge >= 3:
            adjust += 1.5
            reasons.append(f"重賞{ge}走経験あり")
        elif ge == 0:
            adjust -= 1.5
            reasons.append("重賞初挑戦、未知数")

    # 3. 休養間隔パターン
    rb = signals.get("rest_buckets", {})
    last_date = signals.get("last_race_date", "")
    if last_date and race_info.get("today_date"):
        d_last = _parse_date(last_date)
        d_now = _parse_date(race_info["today_date"])
        if d_last and d_now:
            gap = (d_now - d_last).days
            if gap <= 8:    cur_b = "連闘"
            elif gap <= 15: cur_b = "中1週"
            elif gap <= 22: cur_b = "中2週"
            elif gap <= 35: cur_b = "中3-4週"
            elif gap <= 60: cur_b = "中5-8週"
            elif gap <= 120: cur_b = "2-4ヶ月"
            else:           cur_b = "長期休養"
            w, n = rb.get(cur_b, (0, 0))
            if n >= 2:
                rate = w / n
                if rate >= 0.5:
                    adjust += 2.0
                    reasons.append(f"{cur_b}は得意({w}/{n}回好走)")
                elif rate <= 0.0 and n >= 3:
                    adjust -= 1.5
                    reasons.append(f"{cur_b}で過去{n}走全敗")
            # 長期休養 + 経験ゼロは不安
            if cur_b in ("2-4ヶ月", "長期休養") and n == 0:
                adjust -= 0.5
                reasons.append(f"{cur_b}明け、ぶっつけ")

    # 4. 馬体重当日変動（前日比）
    cur_wd = getattr(entry, "weight_diff", None)
    if cur_wd is not None:
        wins = signals.get("weight_diff_wins", [])
        losses = signals.get("weight_diff_losses", [])
        if wins:
            avg_w = sum(wins) / len(wins)
            # 勝った時のレンジに近いか
            if abs(cur_wd - avg_w) <= 4:
                adjust += 1.0
                reasons.append(f"馬体増減{cur_wd:+}kg、勝ち時平均{avg_w:+.1f}kgに近い")
        # 極端な増減
        if cur_wd >= 12:
            adjust -= 1.0
            reasons.append(f"前走比+{cur_wd}kg、馬体増過多")
        elif cur_wd <= -10:
            adjust -= 1.0
            reasons.append(f"前走比{cur_wd}kg、馬体減過多")

    # 5. 過去対戦履歴（head-to-head）
    if rival_records:
        beat, lost = 0, 0
        rival_msgs = []
        # この馬の records から他馬と同走したレースを探すには
        # rival 側の records 内に同じ race_id か同日同会場の記録があるかチェック
        my_records = signals.get("_my_records") or []
        # 簡易版: rival 側の records にて、同日同会場で order を比較
        my_index = {}
        for r in my_records:
            key = (getattr(r, "date", ""), getattr(r, "venue", ""))
            my_index[key] = getattr(r, "order", 99) or 99
        for rival_name, rrecs in rival_records.items():
            for rr in rrecs:
                k = (getattr(rr, "date", ""), getattr(rr, "venue", ""))
                if k in my_index:
                    my_o = my_index[k]
                    th_o = getattr(rr, "order", 99) or 99
                    if my_o < th_o:
                        beat += 1
                        rival_msgs.append(f"{rival_name}に着順上")
                    elif my_o > th_o:
                        lost += 1
                    break  # 各 rival につき一回まで
        if beat + lost >= 1:
            net = beat - lost
            if net >= 2:
                adjust += 2.0
                reasons.append(f"対戦馬に{beat}勝{lost}敗の優勢")
            elif net == 1:
                adjust += 0.8
                reasons.append(f"対戦履歴{beat}勝{lost}敗")
            elif net <= -2:
                adjust -= 1.5
                reasons.append(f"対戦馬に{beat}勝{lost}敗の劣勢")

    return {"adjust": round(adjust, 1), "reasons": reasons[:6]}


if __name__ == "__main__":
    print("advanced_factors_analyzer ready (5 factors)")
