"""Wspólne, buforowane zasoby dla stron aplikacji Streamlit."""
from __future__ import annotations

import subprocess
import sys
import threading

import streamlit as st

import config
from silnik import IndeksHybrydowy, utworz_bota, utworz_klienta, wczytaj_baze_meczow, wczytaj_fragmenty_bazy
from silnik.kolejka import KolejkaFaktow


@st.cache_resource(show_spinner="Wczytuję bazę wiedzy...")
def pobierz_bota():
    return utworz_bota(config)


@st.cache_resource(show_spinner="Wczytuję bazę meczów...")
def pobierz_baze_meczow():
    return wczytaj_baze_meczow(config)


@st.cache_resource
def pobierz_kolejke() -> KolejkaFaktow:
    return KolejkaFaktow(config.PLIK_KOLEJKI)


_BLOKADA_PRZYGOTOWANIA = threading.Lock()  # wspólna dla wszystkich odwiedzających (jeden proces)


def przygotuj_baze_meczow() -> None:
    """W chmurze dysk jest pusty po każdym uruchomieniu serwera, więc pierwsza wizyta pobiera mecze
    (ok. 60 MB plików CSV) i buduje bazę. Osobny proces – po zakończeniu oddaje całą pamięć."""
    if not config.W_CHMURZE or config.PLIK_BAZY_MECZOW.exists():
        return
    with _BLOKADA_PRZYGOTOWANIA:
        if config.PLIK_BAZY_MECZOW.exists():  # ktoś inny zbudował ją w międzyczasie
            return
        with st.spinner("Pierwsze uruchomienie: pobieram historię 361 tys. meczów ATP i WTA (ok. 1–2 minuty)..."):
            wynik = subprocess.run([sys.executable, "-m", "narzedzia.pobierz_mecze", "--bez-biezacych"],
                                   cwd=config.KATALOG_PROJEKTU, capture_output=True, text=True, timeout=1200)
        print(wynik.stdout[-2000:], wynik.stderr[-2000:], flush=True)  # trafia do logów hostingu
        pobierz_baze_meczow.clear()
        pobierz_bota.clear()


def przygotuj_indeks() -> None:
    """W chmurze indeks bazy wiedzy budujemy sam przy pierwszej wizycie (embeddingi liczy API)."""
    if not config.W_CHMURZE or (config.KATALOG_INDEKSU / IndeksHybrydowy.PLIK_FRAGMENTOW).exists():
        return
    with _BLOKADA_PRZYGOTOWANIA:
        if (config.KATALOG_INDEKSU / IndeksHybrydowy.PLIK_FRAGMENTOW).exists():
            return
        komunikat = st.empty()
        komunikat.info("Pierwsze uruchomienie: przygotowuję bazę wiedzy...")
        przebuduj_indeks()
        komunikat.empty()


def przebuduj_indeks() -> int:
    klient = utworz_klienta(config)
    fragmenty = wczytaj_fragmenty_bazy(config.KATALOG_BAZY, config.MAX_ZNAKOW_FRAGMENTU, config.ZAKLADKA_ZNAKOW)
    pasek = st.progress(0.0, text="Liczę embeddingi...")
    indeks = IndeksHybrydowy(klient.embed if config.MODEL_EMBED else None, config.MODEL_EMBED)
    pamiec = IndeksHybrydowy.pamiec_z_katalogu(config.KATALOG_INDEKSU, config.MODEL_EMBED)  # liczymy tylko zmienione
    indeks.zbuduj(fragmenty, postep=lambda z, w: pasek.progress(z / w, text=f"Embeddingi: {z}/{w}"), pamiec=pamiec)
    indeks.zapisz(config.KATALOG_INDEKSU)
    pasek.empty()
    pobierz_bota.clear()
    return len(fragmenty)


INSTRUKCJA_BAZY_MECZOW = """Baza meczów nie jest jeszcze utworzona. W terminalu (w folderze projektu, z aktywnym `.venv`) uruchom:

```
python -m narzedzia.pobierz_mecze
```

Skrypt pobierze pełną historię singla ATP i WTA (1968 – dziś) i zbuduje plik `dane/mecze.sqlite`.
Potem odśwież tę stronę."""
