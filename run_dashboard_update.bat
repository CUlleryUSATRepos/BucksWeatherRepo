@echo off
cd /d C:\Users\Chris Ullery\PycharmProjects\BucksWeatherRepo

call .venv\Scripts\activate.bat

python scripts\build_dashboard_data.py

git add data/dashboard/latest.json
git commit -m "Auto update weather dashboard"
git push origin main

