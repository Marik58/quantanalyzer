@echo off
REM Runs the QuantAnalyzer daily job and appends its output to data\logs\daily_job.log.
REM Schedule it with Windows Task Scheduler: see the instructions at the top of
REM scripts\daily_job.py.
cd /d "%~dp0.."
if not exist data\logs mkdir data\logs
".venv\Scripts\python.exe" scripts\daily_job.py >> data\logs\daily_job.log 2>&1
