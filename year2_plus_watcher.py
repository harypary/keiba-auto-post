"""
年1（直近52週）バックテスト完了検知 → 年2以降を自動継続するワッチャー。
- _progress.json のサイズが5分間増えなくなったら年1完了とみなす
- マーカー year=1 done を書き、continuous_backtest.py を起動（year=2 から）
- そのまま年10まで自動チェーン
"""
import os, sys, io, json, time, subprocess
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

PROGRESS = "data/backtest/_progress.json"
MARKER = "data/backtest/_continuous_marker.json"
STABLE_SEC = 600   # 10分間サイズ変化がなければ完了判定（重み最適化フェーズ含む）

print(f"[watcher] 起動 / 待機中...")

last_size = -1
last_change = time.time()

while True:
    try:
        size = os.path.getsize(PROGRESS) if os.path.exists(PROGRESS) else 0
        if size != last_size:
            last_size = size
            last_change = time.time()
            print(f"[{time.strftime('%H:%M:%S')}] progress.json size={size}")
        elif time.time() - last_change > STABLE_SEC and size > 1000:
            print(f"\n[watcher] {STABLE_SEC}秒間変化なし → 年1バックテスト完了とみなす")
            # マーカー保存
            os.makedirs(os.path.dirname(MARKER), exist_ok=True)
            with open(MARKER, "w", encoding="utf-8") as f:
                json.dump({"year": 1, "status": "done", "ts": time.strftime("%Y-%m-%d %H:%M:%S")}, f)
            print(f"[watcher] continuous_backtest.py を年2から起動")
            subprocess.Popen(
                [sys.executable, "-u", "continuous_backtest.py"],
                env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
                stdout=open("data/backtest/continuous.log", "w", encoding="utf-8"),
                stderr=subprocess.STDOUT,
            )
            print(f"[watcher] 起動完了。終了。")
            break
    except Exception as e:
        print(f"[err] {e}")
    time.sleep(60)
