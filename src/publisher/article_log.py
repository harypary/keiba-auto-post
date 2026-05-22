"""
投稿済み記事の永続ログ。

race_id（または race_key）単位で投稿実績を記録し、別runでも同一レースの
二重投稿を完全に防ぐ。note.com API 障害時もローカルだけで判定可能。

スキーマ:
{
  "by_race_key": {
    "5/22_東京_11R": {
      "race_id": "202605021011",
      "note_id": "n1234abcd",
      "title": "...",
      "url": "https://note.com/.../n/n1234abcd",
      "published_at": "2026-05-22T20:35:12+09:00",
      "verified": true
    }, ...
  },
  "by_title": {"<title>": "<race_key>", ...}
}
"""
import os, json, re, time
from datetime import datetime, timezone, timedelta

LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "published_articles.json")
JST = timezone(timedelta(hours=9))


def _empty():
    return {"by_race_key": {}, "by_title": {}}


def load_log() -> dict:
    if not os.path.exists(LOG_PATH):
        return _empty()
    try:
        with open(LOG_PATH, encoding="utf-8") as f:
            d = json.load(f)
        d.setdefault("by_race_key", {})
        d.setdefault("by_title", {})
        return d
    except Exception:
        return _empty()


def save_log(d: dict) -> None:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def title_to_race_key(title: str) -> str:
    """タイトルから (日付_場_R) のキーを抽出。マッチしなければタイトルそのまま"""
    m = re.search(r"【(\d+/\d+)[^】]*】[^｜]*?([東京京都新潟中山阪神中京福島小倉札幌函館]+)\s*(\d+)R", title or "")
    if m:
        return f"{m.group(1)}_{m.group(2)}_{m.group(3)}R"
    # メインレース（場+R 取れない）はレース名フォールバック
    mm = re.search(r"【(\d+/\d+)[^】]*】([^｜]+)", title or "")
    if mm:
        return f"{mm.group(1)}_{mm.group(2).strip()}"
    return (title or "").strip()[:80]


def is_already_posted(title: str, race_id: str = None) -> bool:
    """指定タイトル/race_id が既に投稿済みか"""
    d = load_log()
    key = title_to_race_key(title)
    if key in d["by_race_key"]:
        return True
    if race_id:
        for entry in d["by_race_key"].values():
            if entry.get("race_id") == race_id:
                return True
    return False


def record_post(title: str, race_id: str, note_id: str, url: str, verified: bool = True) -> None:
    """投稿成功を永続ログに記録"""
    d = load_log()
    key = title_to_race_key(title)
    d["by_race_key"][key] = {
        "race_id": race_id,
        "note_id": note_id,
        "title": title,
        "url": url,
        "published_at": datetime.now(JST).isoformat(),
        "verified": verified,
    }
    d["by_title"][title] = key
    save_log(d)


def get_recent_posts(days: int = 7) -> list:
    """直近N日の投稿一覧"""
    d = load_log()
    cutoff = datetime.now(JST) - timedelta(days=days)
    out = []
    for k, v in d["by_race_key"].items():
        try:
            t = datetime.fromisoformat(v.get("published_at", ""))
            if t >= cutoff:
                out.append(v)
        except Exception:
            pass
    return out


def prune_old(days: int = 60) -> int:
    """N日より古いログを削除。返却=削除件数"""
    d = load_log()
    cutoff = datetime.now(JST) - timedelta(days=days)
    keep = {}
    keep_titles = {}
    removed = 0
    for k, v in d["by_race_key"].items():
        try:
            t = datetime.fromisoformat(v.get("published_at", ""))
            if t >= cutoff:
                keep[k] = v
                keep_titles[v.get("title", "")] = k
            else:
                removed += 1
        except Exception:
            keep[k] = v
            keep_titles[v.get("title", "")] = k
    d["by_race_key"] = keep
    d["by_title"] = keep_titles
    save_log(d)
    return removed


if __name__ == "__main__":
    d = load_log()
    print(f"投稿ログ: {len(d['by_race_key'])}件")
    for k, v in list(d["by_race_key"].items())[-5:]:
        print(f"  {k}: {v.get('title','')[:40]} ({v.get('published_at','')})")
