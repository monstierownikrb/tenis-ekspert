"""Silnik chatbota 'Tenisowy Ekspert' (RAG na lokalnym modelu przez Ollamę)."""
from __future__ import annotations

import sys
from pathlib import Path

from .chatbot import TenisBot
from .indeks import IndeksHybrydowy
from .mecze import BazaMeczow
from .api_klient import KlientAPI
from .ollama_klient import BladOllamy, KlientOllama
from .tekst import Fragment, podziel_markdown, wczytaj_plik

ROZSZERZENIA = {".md", ".txt", ".pdf"}

# Windows: konsola domyślnie nie zawsze używa UTF-8 – bez tego polskie znaki mogą się "sypać".
for _strumien in (sys.stdout, sys.stderr):
    try:
        _strumien.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass


def utworz_klienta(cfg) -> KlientOllama | KlientAPI:
    """Ollama na tym komputerze albo model w chmurze przez API (LLM_DOSTAWCA="api") – reszta kodu jest wspólna."""
    if getattr(cfg, "LLM_DOSTAWCA", "ollama") == "api":
        return KlientAPI(cfg.API_URL, cfg.API_KLUCZ, cfg.MODEL_LLM, cfg.MODEL_EMBED, cfg.TEMPERATURA)
    return KlientOllama(cfg.OLLAMA_HOST, cfg.MODEL_LLM, cfg.MODEL_EMBED, cfg.TEMPERATURA, cfg.NUM_CTX)


def wczytaj_fragmenty_bazy(katalog_bazy: Path, max_znakow: int = 1200, zakladka: int = 150) -> list[Fragment]:
    """Czyta wszystkie pliki .md/.txt/.pdf z katalogu bazy wiedzy (rekurencyjnie) i dzieli je na fragmenty."""
    fragmenty: list[Fragment] = []
    for plik in sorted(katalog_bazy.rglob("*")):
        if plik.is_file() and plik.suffix.lower() in ROZSZERZENIA and not plik.name.startswith((".", "_")):
            wzgledna = plik.relative_to(katalog_bazy).as_posix()
            fragmenty.extend(podziel_markdown(wczytaj_plik(plik), wzgledna, max_znakow, zakladka))
    return fragmenty


def wczytaj_baze_meczow(cfg) -> BazaMeczow | None:
    """Baza meczów jest opcjonalna – jeśli jej nie ma, bot działa na samej bazie wiedzy."""
    sciezka = getattr(cfg, "PLIK_BAZY_MECZOW", None)
    if sciezka is None or not Path(sciezka).exists():
        return None
    return BazaMeczow(sciezka, getattr(cfg, "MAKS_MECZOW_W_KONTEKSCIE", 25))


def utworz_bota(cfg, klient: KlientOllama | None = None) -> TenisBot:
    """Tworzy bota na podstawie ustawień z config.py (indeks musi być wcześniej zbudowany)."""
    klient = klient or utworz_klienta(cfg)
    indeks = IndeksHybrydowy.wczytaj(cfg.KATALOG_INDEKSU, klient.embed if cfg.MODEL_EMBED else None, cfg.MODEL_EMBED)
    return TenisBot(
        klient=klient,
        indeks=indeks,
        katalog_bazy=cfg.KATALOG_BAZY,
        katalog_nauczone=cfg.KATALOG_NAUCZONE,
        katalog_logow=cfg.KATALOG_LOGOW,
        katalog_indeksu=cfg.KATALOG_INDEKSU,
        top_k=cfg.TOP_K,
        historia=cfg.HISTORIA_WIADOMOSCI,
        baza_meczow=wczytaj_baze_meczow(cfg),
    )


__all__ = [
    "TenisBot", "IndeksHybrydowy", "KlientOllama", "KlientAPI", "BladOllamy", "Fragment", "BazaMeczow", "wczytaj_baze_meczow",
    "podziel_markdown", "wczytaj_plik", "wczytaj_fragmenty_bazy", "utworz_bota", "utworz_klienta",
]
