@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Tenisowy Ekspert - instalacja (Windows, PC z karta graficzna) ===
echo.
where ollama >nul 2>nul || (echo [BLAD] Nie znaleziono Ollamy. Zainstaluj ja z https://ollama.com/download i uruchom ten plik ponownie. & pause & exit /b 1)
set "PY=python"
where py >nul 2>nul && set "PY=py -3"
if not exist .venv (
  echo [1/6] Tworze srodowisko Pythona .venv ...
  %PY% -m venv .venv || (echo [BLAD] Nie udalo sie utworzyc .venv - czy Python jest zainstalowany i dodany do PATH? & pause & exit /b 1)
)
call .venv\Scripts\activate.bat
echo [2/6] Instaluje biblioteki Pythona ...
python -m pip install --upgrade pip >nul
pip install -r requirements.txt || (echo [BLAD] Instalacja bibliotek nie powiodla sie. & pause & exit /b 1)
echo [3/6] Pobieram model embeddingow bge-m3 (ok. 1,2 GB) ...
ollama pull bge-m3 || (pause & exit /b 1)
echo [4/6] Pobieram model Bielik 11B v3 (ok. 7 GB) i tworze model tenis-ekspert ...
ollama pull SpeakLeash/bielik-11b-v3.0-instruct:Q4_K_M || (pause & exit /b 1)
ollama create tenis-ekspert -f Modelfile || (pause & exit /b 1)
echo [5/6] Buduje indeks bazy wiedzy (embeddingi) ...
python zbuduj_baze.py || (pause & exit /b 1)
echo [6/6] Pobieram pelna historie meczow ATP i WTA (ok. 100 MB, kilka minut) ...
python -m narzedzia.pobierz_mecze || echo [UWAGA] Nie udalo sie pobrac meczow - chatbot dziala bez nich. Sprobuj pozniej: python -m narzedzia.pobierz_mecze
echo.
echo Gotowe! Uruchom chatbota plikiem: uruchom.bat
pause
