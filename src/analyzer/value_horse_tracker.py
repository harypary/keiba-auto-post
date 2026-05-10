"""
穴馬（バリュー）追跡：
過去レースで「人気下位なのに3着以内に好走した馬」「予想評価以上の着順を残した馬」を
記録し、次走で穴馬候補として優先表示する。

入力: data/backtest/all_horses_training.jsonl（全頭の予想score / odds / finish_order）
出力: data/value_horses.json
  {
    "horse_name": {
      "venue": [(date, finish, odds, notes), ...],
      "next_race_score_boost": 5.0,
      "value_count": 3,
      "last_seen": "2026-04-30"
    }
  }
"""
import os, json
from collections import defaultdict
from glob import glob

VALUE_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "value_horses.json")
TRAINING_JSONL = os.path.join(os.path.dirname(__file__), "..", "..", "data", "backtest", "all_horses_training.jsonl")


def build_value_index() -> dict:
    """all_horses_training.jsonl を全件走査し、穴馬好走パターンを集計"""
    index = defaultdict(lambda: {"events": [], "score_boost": 0.0, "value_count": 0, "last_seen": ""})

    if not os.path.exists(TRAINING_JSONL):
        return {}

    with open(TRAINING_JSONL, encoding="utf-8") as f:
        for line in f:
            try:
                race = json.loads(line)
            except Exception:
                continue

            horses = race.get("horses", [])
            if not horses:
                continue

            # 人気順位を odds から計算（odds 0 のレース＝過去レースで未取得 → score_rank で代替）
            with_odds = [h for h in horses if (h.get("odds", 0) or 0) > 0]
            if len(with_odds) >= 4:
                sorted_by_odds = sorted(with_odds, key=lambda x: x["odds"])
                pop_rank = {h["horse_no"]: i + 1 for i, h in enumerate(sorted_by_odds)}
            else:
                pop_rank = {}   # 空 = pr=None で扱う

            # スコア順位
            score_rank = {h["horse_no"]: i + 1 for i, h in enumerate(
                sorted(horses, key=lambda x: -(x.get("final_score", 0) or 0))
            )}

            for h in horses:
                no = h.get("horse_no")
                name = h.get("horse_name") or ""
                finish = h.get("finish_order", 99)
                odds = h.get("odds", 0) or 0
                pr = pop_rank.get(no, None)
                sr = score_rank.get(no, 99)
                if not name or finish > 5:
                    continue

                # バリュー判定：人気orスコア下位なのに3着以内 = 穴好走
                is_value = False
                if finish <= 3:
                    if pr is not None and pr >= 6:
                        is_value = True
                    if sr >= 7:   # スコア7位以下が3着以内 = サプライズ
                        is_value = True
                    if odds >= 10.0:
                        is_value = True

                if not is_value:
                    continue

                boost = (7 - finish) * 1.2   # 1着=7.2, 2着=6.0, 3着=4.8
                if pr is not None and pr >= 10:
                    boost += 2
                if odds >= 20:
                    boost += 2
                if sr >= 10:
                    boost += 1

                index[name]["events"].append({
                    "date": race.get("date", ""),
                    "venue": race.get("venue", ""),
                    "race_id": race.get("race_id", ""),
                    "finish": finish,
                    "odds": odds,
                    "pop_rank": pr,
                    "score_rank": sr,
                    "boost": round(boost, 1),
                })
                index[name]["last_seen"] = race.get("date", "") or index[name]["last_seen"]
                index[name]["value_count"] += 1
                index[name]["score_boost"] = max(index[name]["score_boost"], boost)

    # 直近1年以内のものに限る（古すぎる穴馬は信頼薄）
    from datetime import date, timedelta
    cutoff = (date.today() - timedelta(days=365)).isoformat()
    filtered = {}
    for name, d in index.items():
        recent = [e for e in d["events"] if e["date"] >= cutoff]
        if recent:
            filtered[name] = {
                "score_boost": max((e["boost"] for e in recent), default=0),
                "value_count": len(recent),
                "last_seen": max((e["date"] for e in recent), default=""),
                "events": recent[-5:],   # 直近5件のみ保存
            }

    os.makedirs(os.path.dirname(VALUE_PATH), exist_ok=True)
    with open(VALUE_PATH, "w", encoding="utf-8") as f:
        json.dump(filtered, f, ensure_ascii=False, indent=2)
    print(f"[value_horse] {len(filtered)}頭の穴馬候補を記録: {VALUE_PATH}")
    return filtered


def load_value_index() -> dict:
    if not os.path.exists(VALUE_PATH):
        return {}
    try:
        with open(VALUE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def get_score_boost(horse_name: str) -> float:
    """指定馬名のバリューブースト点数を返す（comprehensive_scoreが利用）"""
    idx = load_value_index()
    rec = idx.get(horse_name) or {}
    return rec.get("score_boost", 0.0)


if __name__ == "__main__":
    build_value_index()
