@echo off
REM DART自動売買 - タスクスケジューラ用
REM 登録: タスクスケジューラ → 基本タスクの作成 → 毎日 → このbatを指定

cd /d %~dp0
call .venv\Scripts\activate.bat
python src\trader\run.py
