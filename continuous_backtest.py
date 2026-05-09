"""
継続バックテスト拡張：1年分が完了したら自動的に過去2年目→3年目→...と深掘り。
- 各年52週ずつ処理し、毎回 ML 自動再訓練を経由
- レジューム機能あり（_progress.json で重複スキップ）
- 最大10年（520週）まで、または1年分でデータが取れなくなったら停止
- 別プロセスで auto_retrain_ml.py が同時に走る前提
"""
import os, sys, io, json, subprocess, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

MAX_YEARS = 10
WEEKS_PER_YEAR = 52
PROGRESS = "data/backtest/_progress.json"
LOG_DIR = "data/backtest"
MARKER = "data/backtest/_continuous_marker.json"


def _record_count() -> int:
    if not os.path.exists(PROGRESS):
        return 0
    try:
        with open(PROGRESS, encoding="utf-8") as f:
            return len(json.load(f))
    except Exception:
        return 0


def _save_marker(year: int, status: str):
    os.makedirs(os.path.dirname(MARKER), exist_ok=True)
    with open(MARKER, "w", encoding="utf-8") as f:
        json.dump({"year": year, "status": status, "ts": time.strftime("%Y-%m-%d %H:%M:%S")}, f)


def _load_marker() -> dict:
    if not os.path.exists(MARKER):
        return {"year": 0, "status": "init"}
    try:
        with open(MARKER, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"year": 0, "status": "init"}


def run_year(year: int) -> int:
    """year=1: 直近52週、year=2: 53〜104週前、..."""
    skip = (year - 1) * WEEKS_PER_YEAR
    log_path = os.path.join(LOG_DIR, f"run_log_year{year}.txt")
    print(f"\n{'='*60}\n[Year {year}] 過去 {skip+1}〜{skip+WEEKS_PER_YEAR} 週前を処理開始\n{'='*60}")
    _save_marker(year, "running")

    n_before = _record_count()
    proc = subprocess.run(
        [sys.executable, "-u", "run_historical_backtest.py",
         f"--weeks={WEEKS_PER_YEAR}", f"--skip-weeks={skip}", "--max=12"],
        env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
        stdout=open(log_path, "w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
    )
    n_after = _record_count()
    delta = n_after - n_before
    print(f"[Year {year}] 完了: {delta} 件追加 (累計 {n_after})")
    _save_marker(year, "done" if delta > 0 else "no_data")

    # 1年分処理して新規データが少なすぎる（<10件）場合、それ以上遡っても無駄
    if delta < 10:
        print(f"[Year {year}] 新規データ不足 → 拡張停止")
        return 0
    return delta


if __name__ == "__main__":
    print(f"[continuous] 開始: 最大{MAX_YEARS}年（{MAX_YEARS * WEEKS_PER_YEAR}週）まで深掘り")

    last_year = _load_marker().get("year", 0)
    print(f"[continuous] 前回進捗: year {last_year}")

    for y in range(max(1, last_year + 1), MAX_YEARS + 1):
        delta = run_year(y)
        if delta == 0:
            break
        # 各年完了時にML再学習（auto_retrainワッチャーがすでに走っていれば重複してOK）
        try:
            from src.ml.meta_model import train_and_save
            print(f"[continuous] Year {y} 完了でML再訓練")
            r = train_and_save()
            if r:
                print(f"  → 訓練精度 {r.get('accuracy',0)*100:.1f}% (n={r.get('n_samples',0)})")
        except Exception as ex:
            print(f"  [warn] ML再訓練失敗: {ex}")

    print(f"\n[continuous] 全完了。累計 {_record_count()} レース。")
