"""Kolejka faktów do zatwierdzenia – używana, gdy chatbot jest udostępniony w internecie.

Goście mogą proponować nowe fakty i poprawki, ale do bazy wiedzy trafiają one dopiero po zatwierdzeniu
przez autora. Dzięki temu nikt z zewnątrz nie „nauczy” bota nieprawdy ani nie wpisze śmieci.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path

MAKS_DLUGOSC = 2000  # znaków – dłuższe propozycje to raczej dokumenty niż fakty
MAKS_W_KOLEJCE = 200  # ochrona przed zasypaniem kolejki


class KolejkaFaktow:
    def __init__(self, plik: Path):
        self.plik = Path(plik)
        self._blokada = threading.Lock()

    def _wczytaj(self) -> list[dict]:
        try:
            dane = json.loads(self.plik.read_text(encoding="utf-8"))
            return dane if isinstance(dane, list) else []
        except (OSError, ValueError):
            return []

    def _zapisz(self, wpisy: list[dict]) -> None:
        self.plik.parent.mkdir(parents=True, exist_ok=True)
        tymczasowy = self.plik.with_suffix(".tmp")
        tymczasowy.write_text(json.dumps(wpisy, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tymczasowy, self.plik)  # zapis atomowy: plik nigdy nie jest „w połowie” zapisany

    def dodaj(self, tekst: str, zrodlo: str = "gość", rodzaj: str = "fakt") -> dict:
        tekst = (tekst or "").strip()
        if len(tekst) < 10:
            raise ValueError("Fakt jest za krótki – napisz pełne zdanie.")
        if len(tekst) > MAKS_DLUGOSC:
            raise ValueError(f"Fakt jest za długi (maks. {MAKS_DLUGOSC} znaków).")
        wpis = {"id": uuid.uuid4().hex[:12], "czas": datetime.now().isoformat(timespec="seconds"),
                "tekst": tekst, "zrodlo": (zrodlo or "gość").strip()[:200], "rodzaj": rodzaj}
        with self._blokada:
            wpisy = self._wczytaj()
            if len(wpisy) >= MAKS_W_KOLEJCE:
                raise ValueError("Kolejka propozycji jest pełna – spróbuj później.")
            wpisy.append(wpis)
            self._zapisz(wpisy)
        return wpis

    def lista(self) -> list[dict]:
        with self._blokada:
            return self._wczytaj()

    def wyjmij(self, id_wpisu: str) -> dict | None:
        """Usuwa wpis z kolejki i go zwraca (po zatwierdzeniu albo odrzuceniu)."""
        with self._blokada:
            wpisy = self._wczytaj()
            for i, w in enumerate(wpisy):
                if w.get("id") == id_wpisu:
                    wpisy.pop(i)
                    self._zapisz(wpisy)
                    return w
        return None
