"""Indeks wyszukiwania hybrydowego: wektorowy (embeddingi) + słów kluczowych (BM25).

Baza wektorowa jest tu celowo prosta: macierz NumPy z wektorami wszystkich fragmentów
i podobieństwo cosinusowe. Przy kilku tysiącach fragmentów wyszukiwanie trwa milisekundy,
a cały mechanizm da się zrozumieć i opisać w sprawozdaniu.

Dlaczego hybryda?
- Wyszukiwanie wektorowe rozumie znaczenie ("najlepszy zawodnik na mączce" ~ "Nadal, Roland Garros").
- BM25 jest bezbłędne przy dokładnych słowach i liczbach ("Wimbledon 1987").
Wyniki obu metod łączymy algorytmem Reciprocal Rank Fusion (RRF).
"""
from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import numpy as np

from .tekst import Fragment, tokeny

FunkcjaEmbeddingu = Callable[[Sequence[str]], list[list[float]]]


@dataclass
class Trafienie:
    fragment: Fragment
    wynik: float  # wynik po fuzji RRF (im większy, tym lepiej)
    podobienstwo: float  # podobieństwo cosinusowe (diagnostyka)
    bm25: float  # wynik BM25 (diagnostyka)


class BM25:
    """Klasyczny ranking BM25 (Okapi). k1 i b to standardowe wartości z literatury."""

    def __init__(self, dokumenty: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.dokumenty = dokumenty
        self.dl = [len(d) for d in dokumenty]
        self.avgdl = (sum(self.dl) / len(self.dl)) if self.dl else 0.0
        self.tf = [Counter(d) for d in dokumenty]
        df: Counter = Counter()
        for d in dokumenty:
            df.update(set(d))
        n = len(dokumenty)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def wyniki(self, zapytanie: list[str]) -> np.ndarray:
        oceny = np.zeros(len(self.dokumenty), dtype=np.float32)
        for t in set(zapytanie):
            idf = self.idf.get(t)
            if idf is None:
                continue
            for i, tf in enumerate(self.tf):
                f = tf.get(t)
                if f:
                    mianownik = f + self.k1 * (1 - self.b + self.b * self.dl[i] / (self.avgdl or 1))
                    oceny[i] += idf * f * (self.k1 + 1) / mianownik
        return oceny


class IndeksHybrydowy:
    PLIK_WEKTOROW = "wektory.npy"
    PLIK_FRAGMENTOW = "fragmenty.json"
    PLIK_INFO = "info.json"

    def __init__(self, embedder: FunkcjaEmbeddingu | None, model_embed: str = ""):
        """embedder=None – indeks tylko po słowach (BM25), bez wektorów; np. gdy dostawca API nie ma embeddingów."""
        self.embedder = embedder
        self.model_embed = model_embed
        self.fragmenty: list[Fragment] = []
        self.wektory = np.zeros((0, 0), dtype=np.float32)
        self._bm25: BM25 | None = None

    # ---------------------------------------------------------------- budowanie / zapis
    @staticmethod
    def _normalizuj(m: np.ndarray) -> np.ndarray:
        normy = np.linalg.norm(m, axis=1, keepdims=True)
        normy[normy == 0] = 1.0
        return (m / normy).astype(np.float32)

    def _osadz(self, teksty: list[str], paczka: int = 32, postep: Callable[[int, int], None] | None = None) -> np.ndarray:
        if self.embedder is None:
            return np.zeros((len(teksty), 0), dtype=np.float32)
        wektory: list[list[float]] = []
        for i in range(0, len(teksty), paczka):
            wektory.extend(self.embedder(teksty[i : i + paczka]))
            if postep:
                postep(min(i + paczka, len(teksty)), len(teksty))
        return self._normalizuj(np.asarray(wektory, dtype=np.float32))

    def zbuduj(self, fragmenty: list[Fragment], postep: Callable[[int, int], None] | None = None,
               pamiec: dict[str, np.ndarray] | None = None) -> int:
        """Liczy embeddingi fragmentów. `pamiec` (tekst -> wektor z poprzedniego indeksu) pozwala policzyć
        tylko nowe i zmienione fragmenty – na laptopie bez GPU to różnica między kilkoma sekundami a ~15 minutami.
        Zwraca liczbę fragmentów, dla których naprawdę liczono embeddingi."""
        self.fragmenty = list(fragmenty)
        self._bm25 = None
        if not fragmenty:
            self.wektory = np.zeros((0, 0), np.float32)
            return 0
        pamiec = pamiec or {}
        do_policzenia = [i for i, f in enumerate(self.fragmenty) if f.tekst not in pamiec]
        nowe = self._osadz([self.fragmenty[i].tekst for i in do_policzenia], postep=postep) if do_policzenia else None
        wymiar = nowe.shape[1] if nowe is not None else len(next(iter(pamiec.values())))
        self.wektory = np.zeros((len(self.fragmenty), wymiar), dtype=np.float32)
        for i, f in enumerate(self.fragmenty):
            if f.tekst in pamiec:
                self.wektory[i] = pamiec[f.tekst]
        if nowe is not None:
            self.wektory[do_policzenia] = nowe
        return len(do_policzenia)

    @classmethod
    def pamiec_z_katalogu(cls, katalog: Path, model_embed: str) -> dict[str, np.ndarray]:
        """Wektory z istniejącego indeksu (tekst -> wektor), o ile zbudowano go tym samym modelem."""
        try:
            info = json.loads((katalog / cls.PLIK_INFO).read_text(encoding="utf-8"))
            if info.get("model_embed") != model_embed:
                return {}
            wektory = np.load(katalog / cls.PLIK_WEKTOROW)
            dane = json.loads((katalog / cls.PLIK_FRAGMENTOW).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if wektory.ndim != 2 or len(dane) != len(wektory):
            return {}
        return {d["tekst"]: wektory[i] for i, d in enumerate(dane)}

    def dodaj(self, fragmenty: list[Fragment]) -> None:
        """Dopisuje nowe fragmenty bez przebudowy całego indeksu (tak bot 'uczy się' w locie)."""
        if not fragmenty:
            return
        nowe = self._osadz([f.tekst for f in fragmenty])
        istniejace_id = {f.id for f in self.fragmenty}
        if any(f.id in istniejace_id for f in fragmenty):
            raise ValueError("Fragment o takim id już istnieje w indeksie")
        self.fragmenty.extend(fragmenty)
        self.wektory = nowe if self.wektory.size == 0 else np.vstack([self.wektory, nowe])
        self._bm25 = None

    def zapisz(self, katalog: Path) -> None:
        katalog.mkdir(parents=True, exist_ok=True)
        np.save(katalog / self.PLIK_WEKTOROW, self.wektory)
        with open(katalog / self.PLIK_FRAGMENTOW, "w", encoding="utf-8") as f:
            json.dump([fr.jako_slownik() for fr in self.fragmenty], f, ensure_ascii=False)
        with open(katalog / self.PLIK_INFO, "w", encoding="utf-8") as f:
            json.dump({"model_embed": self.model_embed, "liczba_fragmentow": len(self.fragmenty),
                       "wymiar": int(self.wektory.shape[1]) if self.wektory.ndim == 2 and self.wektory.size else 0}, f, ensure_ascii=False)

    @classmethod
    def wczytaj(cls, katalog: Path, embedder: FunkcjaEmbeddingu, model_embed: str = "") -> "IndeksHybrydowy":
        if not (katalog / cls.PLIK_FRAGMENTOW).exists():
            raise FileNotFoundError(f"Brak indeksu w {katalog}. Uruchom najpierw: python zbuduj_baze.py")
        info = {}
        if (katalog / cls.PLIK_INFO).exists():
            info = json.loads((katalog / cls.PLIK_INFO).read_text(encoding="utf-8"))
        if model_embed and info.get("model_embed") and info["model_embed"] != model_embed:
            raise ValueError(
                f"Indeks zbudowano modelem '{info['model_embed']}', a teraz ustawiony jest '{model_embed}'. "
                "Przebuduj indeks: python zbuduj_baze.py"
            )
        idx = cls(embedder, model_embed or info.get("model_embed", ""))
        idx.wektory = np.load(katalog / cls.PLIK_WEKTOROW)
        dane = json.loads((katalog / cls.PLIK_FRAGMENTOW).read_text(encoding="utf-8"))
        idx.fragmenty = [Fragment.ze_slownika(d) for d in dane]
        return idx

    # ---------------------------------------------------------------- wyszukiwanie
    @property
    def bm25(self) -> BM25:
        if self._bm25 is None:
            self._bm25 = BM25([tokeny(f.tekst) for f in self.fragmenty])
        return self._bm25

    def szukaj(self, zapytanie: str, k: int = 6, kandydaci: int = 30, rrf_k: int = 60) -> list[Trafienie]:
        if not self.fragmenty:
            return []
        z_wektorami = self.embedder is not None and self.wektory.ndim == 2 and self.wektory.shape[1] > 0
        if z_wektorami:
            wektor = self._normalizuj(np.asarray(self.embedder([zapytanie]), dtype=np.float32))[0]
            if self.wektory.shape[1] != wektor.shape[0]:
                raise ValueError(
                    f"Wymiar wektorów indeksu ({self.wektory.shape[1]}) nie pasuje do modelu embeddingów "
                    f"({wektor.shape[0]}). Przebuduj indeks: python zbuduj_baze.py"
                )
            podobienstwa = self.wektory @ wektor
        else:
            podobienstwa = np.zeros(len(self.fragmenty), dtype=np.float32)
        oceny_bm25 = self.bm25.wyniki(tokeny(zapytanie))

        ranking_wekt = np.argsort(-podobienstwa)[:kandydaci] if z_wektorami else []
        ranking_bm25 = [i for i in np.argsort(-oceny_bm25)[:kandydaci] if oceny_bm25[i] > 0]

        fuzja: dict[int, float] = {}
        for pozycja, i in enumerate(ranking_wekt):
            fuzja[int(i)] = fuzja.get(int(i), 0.0) + 1.0 / (rrf_k + pozycja + 1)
        for pozycja, i in enumerate(ranking_bm25):
            fuzja[int(i)] = fuzja.get(int(i), 0.0) + 1.0 / (rrf_k + pozycja + 1)

        najlepsze = sorted(fuzja.items(), key=lambda x: -x[1])[:k]
        return [
            Trafienie(self.fragmenty[i], wynik, float(podobienstwa[i]), float(oceny_bm25[i]))
            for i, wynik in najlepsze
        ]
