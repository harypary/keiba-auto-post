"""
バックテスト進行中に ML モデルを自動再訓練するワッチャー。
data/backtest/_progress.json のサンプル数増加を検知し、50件以上増えたら ML再学習。
"""
import os, sys, io, json, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(__file__))

PROGRESS = "data/backtest/_progress.json"
last_n = 0

while True:
    try:
        if os.path.exists(PROGRESS):
            with open(PROGRESS, encoding="utf-8") as f:
                d = json.load(f)
            n = len(d)
            if n - last_n >= 50:
                print(f"[{time.strftime('%H:%M:%S')}] 進捗 {last_n} → {n}: ML再訓練開始")
                from src.ml.meta_model import train_and_save
                r = train_and_save()
                if r:
                    print(f"[{time.strftime('%H:%M:%S')}] → 訓練精度 {r.get('accuracy',0)*100:.1f}% (n={r.get('n_samples',0)})")
                last_n = n
    except Exception as e:
        print(f"[err] {e}")
    time.sleep(120)
