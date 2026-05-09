"""
完全自動スケジューラ
- 金曜21時: 土曜全レース予想投稿
- 土曜21時: 日曜全レース予想投稿
- 日曜・月曜早朝: レース結果取得 & キャッシュ更新
"""
import schedule
import time
import logging
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from datetime import date, timedelta

from config.settings import OUTPUT_DIR, CACHE_DIR

# ログ設定
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/scheduler.log", encoding="utf-8"),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)


def post_tomorrow_races():
    """翌日のレース予想を投稿"""
    from src.pipeline import run_pipeline
    tomorrow = date.today() + timedelta(days=1)
    logger.info(f"予想投稿開始: {tomorrow}")
    try:
        run_pipeline(target_date=tomorrow, publish=True, save_files=True)
        logger.info(f"投稿完了: {tomorrow}")
    except Exception as e:
        logger.error(f"投稿エラー: {e}", exc_info=True)


def refresh_cache_after_races():
    """レース終了後にキャッシュを更新（翌日の精度向上）"""
    from src.pipeline import invalidate_cache
    logger.info("キャッシュ更新（古いデータをクリア）")
    try:
        invalidate_cache()   # 全キャッシュクリア → 次回自動再取得
        logger.info("キャッシュクリア完了")
    except Exception as e:
        logger.error(f"キャッシュ更新エラー: {e}", exc_info=True)


def update_race_results():
    """日曜・月曜: 前日レース結果を記録（将来の精度向上用）"""
    logger.info("レース結果記録処理")
    # TODO: レース結果をDBに記録して統計モデルの精度を継続改善
    # 現在はキャッシュクリアのみ
    refresh_cache_after_races()


def setup_schedule():
    os.makedirs("logs", exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)

    # 予想投稿スケジュール
    schedule.every().friday.at("21:00").do(post_tomorrow_races)    # 土曜レース予想
    schedule.every().saturday.at("21:00").do(post_tomorrow_races)  # 日曜レース予想

    # データ更新スケジュール（レース終了後）
    schedule.every().sunday.at("18:30").do(update_race_results)    # 土曜分更新
    schedule.every().monday.at("07:00").do(update_race_results)    # 日曜分更新

    logger.info("スケジューラ設定完了")
    logger.info("  金曜 21:00 -> 土曜レース予想投稿")
    logger.info("  土曜 21:00 -> 日曜レース予想投稿")
    logger.info("  日曜 18:30 -> データ更新")
    logger.info("  月曜 07:00 -> データ更新")


def run_forever():
    setup_schedule()
    logger.info("スケジューラ起動 - 待機中...")
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    import argparse
    from datetime import datetime

    parser = argparse.ArgumentParser()
    parser.add_argument("--date",    help="対象日 YYYYMMDD")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--clear-cache", action="store_true")
    args = parser.parse_args()

    if args.clear_cache:
        from src.pipeline import invalidate_cache
        invalidate_cache()
    elif args.date:
        from src.pipeline import run_pipeline
        t = datetime.strptime(args.date, "%Y%m%d").date()
        run_pipeline(t, publish=not args.dry_run, save_files=True)
    else:
        run_forever()
