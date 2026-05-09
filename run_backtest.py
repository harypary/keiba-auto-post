"""
先週の実際のレースでバックテスト実行
2026/05/03(土) と 2026/05/04(日) の結果で検証
"""
import sys, os, io
sys.path.insert(0, os.path.dirname(__file__))
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
except Exception:
    pass

from datetime import date
from src.validator.backtest import run_backtest

if __name__ == "__main__":
    # 先週の土日で検証
    dates = [date(2026, 5, 3), date(2026, 5, 4)]
    report = run_backtest(dates)
