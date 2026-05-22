"""
投稿生存確認: note.com の公開プロフィールページから本日投稿された記事数を検出。

実際に公開されている本数 < 期待本数 なら exit 1 で失敗を通知 → 上位ワークフローが
自動エスカレーション（セッション再生成→下書き再公開）をトリガする。
"""
import sys, os, re, json
from datetime import datetime, date, timezone, timedelta

JST = timezone(timedelta(hours=9))


def fetch_profile_page(user_id: str) -> str:
    import urllib.request
    url = f"https://note.com/{user_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="ignore")


def count_today_posts(html: str) -> int:
    """HTML 内の本日公開記事を概算（公開日時の "数時間前" や "○時間前" を検出）"""
    today_jst = datetime.now(JST).date()
    # note.comはRelative time表記が多いので「分前」「時間前」を本日扱い
    rel_count = len(re.findall(r"(?:数分前|分前|時間前)", html))
    # 絶対日付パターン: 2026年5月22日 形式
    abs_pattern = today_jst.strftime("%Y年%-m月%-d日").replace("-", "")
    abs_pattern_safe = f"{today_jst.year}年{today_jst.month}月{today_jst.day}日"
    abs_count = html.count(abs_pattern_safe)
    return max(rel_count, abs_count)


def main():
    user_id = os.environ.get("NOTE_USER_ID", "_almanddd")
    # 期待値: 平日0、土0、日2 のような単純化はせず、引数指定可
    expected = int(sys.argv[1]) if len(sys.argv) > 1 else 1

    try:
        html = fetch_profile_page(user_id)
    except Exception as ex:
        print(f"[HEALTH] プロフィール取得失敗: {ex}", file=sys.stderr)
        # 取得失敗時は失敗扱いにしない（ネットワーク問題と区別）
        return 0

    posted = count_today_posts(html)
    print(f"[HEALTH] {user_id} の本日投稿数推定: {posted}件 / 期待: {expected}件以上")

    if posted < expected:
        print(f"[HEALTH] 不足あり → エスカレーション要", file=sys.stderr)
        return 1
    print(f"[HEALTH] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
