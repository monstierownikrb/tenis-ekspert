"""Przetwarzanie tekstu: normalizacja, tokenizacja (dla BM25) i dzielenie dokumentów na fragmenty.

Dlaczego to jest potrzebne:
- Model embeddingów i wyszukiwarka słów kluczowych (BM25) działają na krótkich fragmentach,
  a nie na całych plikach. Krótszy fragment = trafniejsze dopasowanie do pytania.
- Język polski ma odmianę (Wimbledon / Wimbledonie, Nadal / Nadala), więc dla BM25
  używamy prostego "stemmingu": bierzemy pierwsze 5 liter słowa bez polskich znaków.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

# Litery, których unicodedata nie rozkłada na literę bazową + akcent.
_ZAMIANY = str.maketrans({"ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "ø": "o", "Ø": "O", "ß": "ss"})

_SLOWA_POMIJANE = {
    "a", "i", "w", "z", "o", "u", "na", "do", "od", "po", "za", "ze", "we", "się", "sie", "to", "jest",
    "czy", "jak", "co", "kto", "ile", "jaki", "jaka", "jakie", "który", "ktory", "która", "ktora",
    "które", "ktore", "kiedy", "gdzie", "oraz", "albo", "lub", "że", "ze", "nie", "tak", "był",
    "byl", "była", "byla", "było", "bylo", "roku", "rok", "the", "of", "and", "in",
}

_DLUGOSC_RDZENIA = 5


def bez_ogonkow(tekst: str) -> str:
    """'Świątek Djoković Łódź' -> 'Swiatek Djokovic Lodz'."""
    tekst = tekst.translate(_ZAMIANY)
    rozlozony = unicodedata.normalize("NFKD", tekst)
    return "".join(z for z in rozlozony if not unicodedata.combining(z))


_PARTYKULY_UZUPELNIENIA = re.compile(r"^\W*(a|i|oraz|ale|tylko|to|no|czyli|zas)\b")
_ZAIMKI_OSOBOWE = re.compile(r"\b(on|ona|oni|one|jego|jej|ich|nim|nia|niego|niej|nich|tam|wtedy|tamten\w*)\b")


def wyglada_na_uzupelniajace(pytanie: str) -> bool:
    """Czy pytanie wyraźnie nawiązuje do poprzedniego? („A na trawie?”, „A ile razy on wygrał?”)

    Sama krótkość pytania NIE wystarcza: „Ile tytułów zdobył Hurkacz?” jest krótkie,
    ale to nowe, samodzielne pytanie.
    """
    t = bez_ogonkow(pytanie.lower()).strip()
    return bool(_PARTYKULY_UZUPELNIENIA.search(t) or _ZAIMKI_OSOBOWE.search(t))


def tokeny(tekst: str) -> list[str]:
    """Tokeny do wyszukiwania BM25: małe litery, bez ogonków, rdzeń = 5 pierwszych znaków."""
    tekst = bez_ogonkow(tekst.lower())
    slowa = re.findall(r"[a-z0-9]+", tekst)
    wynik = []
    for s in slowa:
        if s in _SLOWA_POMIJANE:
            continue
        if s.isdigit():
            wynik.append(s)  # lata i liczby zostawiamy w całości (1987, 24, 14)
        elif len(s) >= 2:
            wynik.append(s[:_DLUGOSC_RDZENIA])
    return wynik


@dataclass
class Fragment:
    """Jeden fragment bazy wiedzy (to on trafia do indeksu i do promptu modelu)."""

    id: str
    tekst: str
    zrodlo: str  # ścieżka pliku względem katalogu bazy wiedzy
    tytul: str  # tytuł dokumentu + nagłówek sekcji
    meta: dict = field(default_factory=dict)

    def jako_slownik(self) -> dict:
        return {"id": self.id, "tekst": self.tekst, "zrodlo": self.zrodlo, "tytul": self.tytul, "meta": self.meta}

    @staticmethod
    def ze_slownika(d: dict) -> "Fragment":
        return Fragment(id=d["id"], tekst=d["tekst"], zrodlo=d["zrodlo"], tytul=d["tytul"], meta=d.get("meta", {}))


def _rozbij(tekst: str, max_znakow: int) -> list[str]:
    """Rozbija tekst na kawałki <= max_znakow: najpierw po liniach, potem po zdaniach, w ostateczności po słowach."""
    if len(tekst) <= max_znakow:
        return [tekst]
    for wzorzec in (r"\n", r"(?<=[.!?;])\s+", r"\s+"):
        czesci = [c for c in re.split(wzorzec, tekst) if c.strip()]
        if len(czesci) > 1:
            wynik: list[str] = []
            for c in czesci:
                wynik.extend(_rozbij(c, max_znakow))
            return wynik
    return [tekst[i : i + max_znakow] for i in range(0, len(tekst), max_znakow)]


def _podziel_dlugi(tekst: str, max_znakow: int, zakladka: int) -> list[str]:
    """Dzieli za długą sekcję na fragmenty ~max_znakow, z niewielką zakładką (powtórzeniem końcówki)."""
    if len(tekst) <= max_znakow:
        return [tekst]
    czesci: list[str] = []
    for akapit in (a.strip() for a in re.split(r"\n\s*\n", tekst)):
        if akapit:
            czesci.extend(_rozbij(akapit, max_znakow - zakladka))
    wynik: list[str] = []
    biezacy = ""
    for c in czesci:
        if biezacy and len(biezacy) + len(c) + 1 > max_znakow:
            wynik.append(biezacy.strip())
            ogon = biezacy[-zakladka:] if zakladka else ""
            ogon = ogon[ogon.find(" ") + 1 :] if " " in ogon else ""
            biezacy = (ogon + " … ") if ogon else ""
        biezacy += c + "\n"
    if biezacy.strip():
        wynik.append(biezacy.strip())
    return wynik


def podziel_markdown(tresc: str, zrodlo: str, max_znakow: int = 1200, zakladka: int = 150) -> list[Fragment]:
    """Dzieli plik Markdown na fragmenty według nagłówków '## '.

    Każdy fragment zaczyna się od tytułu dokumentu i nagłówka sekcji – dzięki temu
    nawet krótki fragment "wie", czego dotyczy (np. "Wimbledon – rekordy").
    """
    tresc = tresc.replace("\r\n", "\n")
    tytul_dok = Path(zrodlo).stem.replace("_", " ")
    m = re.search(r"^# (.+)$", tresc, flags=re.M)
    if m:
        tytul_dok = m.group(1).strip()

    sekcje: list[tuple[str, str]] = []
    biezacy_naglowek = ""
    bufor: list[str] = []
    for linia in tresc.split("\n"):
        if linia.startswith("# ") and not linia.startswith("## "):
            continue  # tytuł dokumentu już mamy
        if linia.startswith("## "):
            if "".join(bufor).strip():
                sekcje.append((biezacy_naglowek, "\n".join(bufor).strip()))
            biezacy_naglowek = linia[3:].strip()
            bufor = []
        else:
            bufor.append(linia)
    if "".join(bufor).strip():
        sekcje.append((biezacy_naglowek, "\n".join(bufor).strip()))

    fragmenty: list[Fragment] = []
    for nr_sekcji, (naglowek, tekst) in enumerate(sekcje):
        tytul = f"{tytul_dok} – {naglowek}" if naglowek else tytul_dok
        for nr_czesci, czesc in enumerate(_podziel_dlugi(tekst, max_znakow, zakladka)):
            fragmenty.append(
                Fragment(
                    id=f"{zrodlo}#{nr_sekcji}.{nr_czesci}",
                    tekst=f"{tytul}\n{czesc}",
                    zrodlo=zrodlo,
                    tytul=tytul,
                )
            )
    return fragmenty


def wczytaj_plik(sciezka: Path) -> str:
    """Wczytuje .md / .txt (UTF-8) lub .pdf (jeśli zainstalowano pypdf)."""
    if sciezka.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("Do wczytywania PDF zainstaluj pakiet: pip install pypdf") from e
        czytnik = PdfReader(str(sciezka))
        strony = [s.extract_text() or "" for s in czytnik.pages]
        return f"# {sciezka.stem}\n\n" + "\n\n".join(strony)
    return sciezka.read_text(encoding="utf-8", errors="replace")
