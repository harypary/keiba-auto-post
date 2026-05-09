@echo off
chcp 65001 >nul
echo 競馬予想 note自動投稿スケジューラ 起動中...
cd /d "%~dp0"

:: 仮想環境があれば有効化
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

:: ログフォルダ作成
if not exist logs mkdir logs

:: スケジューラ常駐起動
python main.py

pause
