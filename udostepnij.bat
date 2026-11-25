@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem ===========================================================================================
rem  Udostepnia chatbota w internecie: Streamlit dziala na tym komputerze (Bielik na karcie
rem  graficznej), a cloudflared tworzy bezplatny publiczny adres https://....trycloudflare.com
rem  Nie trzeba konta, domeny ani otwierania portow w routerze.
rem ===========================================================================================
if not exist .venv\Scripts\python.exe goto brak_venv

call :znajdz_cloudflared
if defined CF goto mamy_cf
echo Instaluje cloudflared - program, ktory tworzy publiczny adres strony (jednorazowo)...
winget install --id Cloudflare.cloudflared -e --accept-source-agreements --accept-package-agreements
call :znajdz_cloudflared
if defined CF goto mamy_cf
echo.
echo [BLAD] Nie znalazlem programu cloudflared.
echo Zamknij to okno i uruchom udostepnij.bat jeszcze raz. Jesli nie pomoze, zainstaluj recznie:
echo     winget install --id Cloudflare.cloudflared
pause
exit /b 1

:mamy_cf
echo === Tenisowy Ekspert - udostepnianie w internecie ===
echo Kazdy, kto dostanie link, bedzie mogl rozmawiac z chatbotem.
echo Fakty i poprawki od gosci trafia do bazy dopiero po Twoim zatwierdzeniu.
echo.
:haslo
set "TENIS_HASLO="
set /p "TENIS_HASLO=Ustaw haslo autora (wpiszesz je w aplikacji w 'Panelu autora'): "
if "%TENIS_HASLO%"=="" goto haslo

start "Tenisowy Ekspert - serwer (nie zamykaj)" .venv\Scripts\python.exe -m streamlit run app.py --server.port 8501 --server.headless true --browser.gatherUsageStats false
echo Czekam, az chatbot wystartuje...
timeout /t 8 /nobreak >nul
echo.
echo ============================================================================================
echo  Za chwile ponizej pojawi sie publiczny adres w ramce, np.  https://cos-tam.trycloudflare.com
echo  Skopiuj go (zaznacz mysza i Enter) i wyslij prowadzacemu.
echo  Adres dziala, dopoki ten komputer jest wlaczony, a to okno i okno serwera sa otwarte.
echo  Kazde uruchomienie daje NOWY adres. Zakonczenie: Ctrl+C tutaj i zamkniecie okna serwera.
echo ============================================================================================
echo.
"%CF%" tunnel --url http://localhost:8501
pause
exit /b 0

:znajdz_cloudflared
rem winget dopisuje cloudflared do PATH dopiero w nowym oknie, dlatego sprawdzamy tez typowe sciezki
set "CF="
for /f "delims=" %%i in ('where cloudflared 2^>nul') do if not defined CF set "CF=%%i"
if not defined CF if exist "%ProgramFiles(x86)%\cloudflared\cloudflared.exe" set "CF=%ProgramFiles(x86)%\cloudflared\cloudflared.exe"
if not defined CF if exist "%ProgramFiles%\cloudflared\cloudflared.exe" set "CF=%ProgramFiles%\cloudflared\cloudflared.exe"
if not defined CF if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\cloudflared.exe" set "CF=%LOCALAPPDATA%\Microsoft\WinGet\Links\cloudflared.exe"
exit /b 0

:brak_venv
echo [BLAD] Brak folderu .venv - najpierw uruchom instaluj.bat
pause
exit /b 1
