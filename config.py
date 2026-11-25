"""Ustawienia projektu. Każdą wartość można nadpisać zmienną środowiskową o tej samej nazwie,
np. w PowerShell:   $env:MODEL_LLM = "SpeakLeash/bielik-4.5b-v3.0-instruct:Q8_0"
     w bash:        export MODEL_LLM=SpeakLeash/bielik-4.5b-v3.0-instruct:Q8_0
"""
import os
from pathlib import Path

KATALOG_PROJEKTU = Path(__file__).resolve().parent


def _surowa(nazwa: str) -> str | None:
    """Wartość ze zmiennej środowiskowej albo – na Streamlit Community Cloud – z ustawień „Secrets”."""
    if nazwa in os.environ:
        return os.environ[nazwa]
    try:
        import streamlit as st

        if nazwa in st.secrets:
            return str(st.secrets[nazwa])
    except Exception:  # noqa: BLE001 – brak pliku secrets.toml to normalna sytuacja lokalnie
        pass
    return None


def _env(nazwa: str, domyslna):
    wartosc = _surowa(nazwa)
    if wartosc is None:
        return domyslna
    return type(domyslna)(wartosc)


# --- Skąd bierzemy model językowy --------------------------------------------------------------
# "ollama" – model działa na tym komputerze (Bielik przez Ollamę) – domyślnie.
# "api"    – model w chmurze przez API zgodne z OpenAI (np. Mistral) – do wersji na stronie internetowej
#            (Streamlit Community Cloud), gdzie nie ma karty graficznej ani Ollamy.
LLM_DOSTAWCA = _env("LLM_DOSTAWCA", "ollama").strip().lower()
W_CHMURZE = LLM_DOSTAWCA == "api"
API_URL = _env("API_URL", "https://api.mistral.ai/v1")
API_KLUCZ = _env("API_KLUCZ", "")
# Limit długości odpowiedzi modelu z API. Spory zapas, bo modele „myślące” (np. Gemini) liczą do niego też myślenie.
API_MAKS_TOKENOW = _env("API_MAKS_TOKENOW", 4096)

# --- Ollama -------------------------------------------------------------------------------
OLLAMA_HOST = _env("OLLAMA_HOST", "http://localhost:11434")

# Model językowy (LLM). Lokalnie "tenis-ekspert" tworzymy z pliku Modelfile poleceniem:
#   ollama create tenis-ekspert -f Modelfile
MODEL_LLM = _env("MODEL_LLM", "mistral-small-latest" if W_CHMURZE else "tenis-ekspert")

# Model embeddingów – zamienia tekst na wektor liczb. bge-m3 (lokalnie) i mistral-embed (API) dobrze znają polski.
# Pusta wartość = wyszukiwanie tylko po słowach (BM25), np. gdy dostawca API nie ma embeddingów.
MODEL_EMBED = _env("MODEL_EMBED", "mistral-embed" if W_CHMURZE else "bge-m3")

# --- Parametry generowania ------------------------------------------------------------------
TEMPERATURA = _env("TEMPERATURA", 0.2)  # niska = mniej "fantazji", więcej faktów
NUM_CTX = _env("NUM_CTX", 8192)  # okno kontekstu modelu (w tokenach)

# --- RAG ------------------------------------------------------------------------------------
TOP_K = _env("TOP_K", 6)  # ile fragmentów bazy wiedzy wklejamy do promptu
MAX_ZNAKOW_FRAGMENTU = _env("MAX_ZNAKOW_FRAGMENTU", 1200)
ZAKLADKA_ZNAKOW = _env("ZAKLADKA_ZNAKOW", 150)
HISTORIA_WIADOMOSCI = _env("HISTORIA_WIADOMOSCI", 6)  # ile ostatnich wiadomości rozmowy pamiętamy

# --- Ścieżki --------------------------------------------------------------------------------
KATALOG_BAZY = KATALOG_PROJEKTU / "baza_wiedzy"
KATALOG_NAUCZONE = KATALOG_BAZY / "nauczone"
KATALOG_WGRANE = KATALOG_BAZY / "wgrane"
KATALOG_INDEKSU = KATALOG_PROJEKTU / "indeks"
KATALOG_LOGOW = KATALOG_PROJEKTU / "logi"

# --- Baza meczów (pełna historia ATP/WTA) – tworzy ją: python -m narzedzia.pobierz_mecze ---------
KATALOG_MECZOW_ZRODLA = KATALOG_PROJEKTU / "dane_zrodlowe" / "mecze"
PLIK_BAZY_MECZOW = KATALOG_PROJEKTU / "dane" / "mecze.sqlite"
MAKS_MECZOW_W_KONTEKSCIE = _env("MAKS_MECZOW_W_KONTEKSCIE", 25)  # ile meczów wklejamy do promptu

# --- Udostępnianie w internecie (udostepnij.bat) ----------------------------------------------
# Gdy ustawione jest hasło (zmienna TENIS_HASLO), aplikacja działa w TRYBIE PUBLICZNYM: każdy z linkiem może
# rozmawiać z chatbotem, ale fakty i poprawki od gości czekają na zatwierdzenie przez autora, a wgrywanie
# dokumentów i przebudowa indeksu są dostępne dopiero po wpisaniu hasła w „Panelu autora”.
HASLO_ADMINA = _env("TENIS_HASLO", "")
TRYB_PUBLICZNY = bool(HASLO_ADMINA)
PLIK_KOLEJKI = KATALOG_LOGOW / "do_zatwierdzenia.json"
