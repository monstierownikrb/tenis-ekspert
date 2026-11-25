#!/usr/bin/env bash
# Instalacja na Linuksie (Ubuntu).  ./instaluj.sh         -> Bielik 11B (komputer z GPU)
#                                   ./instaluj.sh laptop  -> Bielik 4.5B (laptop / CPU)
set -euo pipefail
cd "$(dirname "$0")"
# ROS 2 (i inne środowiska) ustawiają PYTHONPATH – odcinamy go, żeby .venv używał tylko swoich bibliotek
unset PYTHONPATH
command -v ollama >/dev/null || { echo "Brak Ollamy. Zainstaluj: curl -fsSL https://ollama.com/install.sh | sh"; exit 1; }
if [ "${1:-}" = "laptop" ]; then
  MODEL="SpeakLeash/bielik-4.5b-v3.0-instruct:Q8_0"; MODELFILE="Modelfile.laptop"
else
  MODEL="SpeakLeash/bielik-11b-v3.0-instruct:Q4_K_M"; MODELFILE="Modelfile"
fi
[ -d .venv ] || { echo "[1/6] Tworzę środowisko .venv"; python3 -m venv .venv; }
source .venv/bin/activate
echo "[2/6] Instaluję biblioteki"; pip install -q --upgrade pip; pip install -q -r requirements.txt
echo "[3/6] Pobieram bge-m3";      ollama pull bge-m3
echo "[4/6] Pobieram $MODEL";      ollama pull "$MODEL"; ollama create tenis-ekspert -f "$MODELFILE"
echo "[5/6] Buduję indeks";        python zbuduj_baze.py
echo "[6/6] Pobieram historię meczów"; python -m narzedzia.pobierz_mecze || echo "UWAGA: nie udało się pobrać meczów (spróbuj później)"
echo "Gotowe! Uruchom: bash uruchom.sh"
