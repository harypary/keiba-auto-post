#!/usr/bin/env python3
"""
中央競馬予想 note自動投稿システム
Usage:
  python main.py                          # スケジューラ常駐起動
  python main.py --date 20260510          # 指定日のみ実行
  python main.py --dry-run --date 20260510 # ファイル保存のみ（テスト）
  python main.py --run-now saturday       # 土曜用を今すぐ実行
"""
import sys
import io
import os
sys.path.insert(0, os.path.dirname(__file__))
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
except Exception:
    pass

if __name__ == "__main__":
    from src.scheduler.auto_scheduler import run_forever
    import argparse
    from datetime import date, timedelta, datetime

    parser = argparse.ArgumentParser(description="競馬予想note自動投稿システム")
    parser.add_argument("--date", help="対象日 YYYYMMDD")
    parser.add_argument("--dry-run", action="store_true", help="noteに投稿せずファイル保存のみ")
    parser.add_argument("--run-now", choices=["saturday", "sunday"], help="今すぐ実行")
    parser.add_argument("--clear-cache", action="store_true", help="キャッシュクリア")
    args = parser.parse_args()

    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    if args.clear_cache:
        from src.pipeline import invalidate_cache
        invalidate_cache()
    elif args.date or args.run_now:
        from src.pipeline import run_pipeline
        if args.date:
            target = datetime.strptime(args.date, "%Y%m%d").date()
        elif args.run_now == "saturday":
            # 直近の土曜（今日が土曜なら今日、それ以外は次の土曜）
            today = date.today()
            days = (5 - today.weekday()) % 7
            target = today + timedelta(days=days)
        elif args.run_now == "sunday":
            # 直近の日曜（今日が日曜なら今日、それ以外は次の日曜）
            today = date.today()
            days = (6 - today.weekday()) % 7
            target = today + timedelta(days=days)
        else:
            target = date.today() + timedelta(days=1)
        publish = not args.dry_run
        print(f"対象日: {target}  投稿: {publish}")
        run_pipeline(target_date=target, publish=publish, save_files=True)
    else:
        run_forever()
