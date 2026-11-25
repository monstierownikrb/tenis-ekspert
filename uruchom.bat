@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (echo [BLAD] Brak folderu .venv - najpierw uruchom instaluj.bat & pause & exit /b 1)
echo === Tenisowy Ekspert ===
echo Uruchamiam aplikacje. Za kilka sekund otworzy sie przegladarka: http://localhost:8501
echo Jesli sie nie otworzy, wpisz ten adres recznie w przegladarce.
echo Aby zatrzymac chatbota: Ctrl+C albo zamknij to okno.
echo.
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 6; Start-Process 'http://localhost:8501'"
.venv\Scripts\python.exe -m streamlit run app.py --server.port 8501 --server.headless true --browser.gatherUsageStats false
echo.
echo [INFO] Chatbot zostal zatrzymany. Jesli wyzej jest komunikat o bledzie, zrob zrzut ekranu.
pause
