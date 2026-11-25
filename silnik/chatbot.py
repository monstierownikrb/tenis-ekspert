"""Logika chatbota: wyszukanie wiedzy (RAG) -> zbudowanie promptu -> odpowiedź modelu -> uczenie się."""
from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Iterator

from .indeks import IndeksHybrydowy, Trafienie
from .mecze import BazaMeczow, WynikMeczow
from .ollama_klient import KlientOllama
from .tekst import Fragment, podziel_markdown, wczytaj_plik, wyglada_na_uzupelniajace

MIESIACE = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia",
            "września", "października", "listopada", "grudnia"]


def dzisiaj_po_polsku(d: date | None = None) -> str:
    d = d or date.today()
    return f"{d.day} {MIESIACE[d.month - 1]} {d.year}"


PROMPT_SYSTEMOWY_RAG = """Jesteś „Tenisowym Ekspertem” – chatbotem, który wie wszystko o tenisie: historię, zasady, \
turnieje, rekordy, zawodników, technikę i bieżące wydarzenia. Dzisiaj jest {dzisiaj}.

ZASADY:
1. Odpowiadaj WYŁĄCZNIE na podstawie fragmentów z sekcji KONTEKST. Nie dopowiadaj faktów z pamięci.
2. Jeśli w KONTEKŚCIE nie ma odpowiedzi, powiedz wprost: „Nie mam tej informacji w swojej bazie wiedzy.” \
i zaproponuj, o co można zapytać zamiast tego. Nie zgaduj dat, wyników ani liczb.
3. Po każdym zdaniu z faktem dodaj numer źródła w nawiasie kwadratowym, np. [2].
4. Odpowiadaj po polsku, konkretnie i krótko (zwykle 2–6 zdań). Listy stosuj tylko przy wyliczeniach.
5. Jeśli pytanie nie dotyczy tenisa, uprzejmie odpowiedz, że jesteś ekspertem od tenisu i chętnie \
odpowiesz na pytanie o tenis.
6. Uważaj na płeć i konkurencję: turnieje mają osobne konkurencje mężczyzn i kobiet. Jeśli pytanie \
jest niejednoznaczne (np. „kto wygrał Wimbledon 2019?”), podaj oba wyniki.
7. Dane „bieżące” (rankingi, sezon) obowiązują na dzień podany w źródle – zaznacz to w odpowiedzi.
8. Blok [M] zawiera liczby i listy meczów policzone dokładnie z bazy wszystkich meczów ATP/WTA. Przy pytaniach \
o bilanse, wyniki konkretnych meczów i statystyki opieraj się na [M] i cytuj go jako [M]. Baza obejmuje turnieje \
głównego cyklu (bez większości challengerów i kwalifikacji), więc liczby mogą minimalnie różnić się od oficjalnych.
9. Pytanie bez nazwiska (np. „Ile razy wygrał z Djokoviciem?”) dotyczy zawodnika z poprzedniego pytania – \
o kogo chodzi, mówi „Doprecyzowanie” pod pytaniem i pierwsza linia bloku [M]. Odpowiedz normalnie. Wynik 0 też \
jest odpowiedzią (np. „ani razu – przegrał wszystkie 8 meczów”), nie odmawiaj z tego powodu."""

PROMPT_SYSTEMOWY_BEZ_RAG = """Jesteś „Tenisowym Ekspertem” – chatbotem, który odpowiada na pytania o tenis. \
Dzisiaj jest {dzisiaj}. Odpowiadaj po polsku, krótko i konkretnie. Jeśli czegoś nie wiesz, powiedz to."""


@dataclass
class Odpowiedz:
    """Wynik jednego pytania: strumień tekstu + źródła, z których korzystał model."""

    pytanie: str
    trafienia: list[Trafienie]
    strumien: Iterator[str]
    mecze: WynikMeczow | None = None
    tekst: str = ""
    czas: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


class TenisBot:
    def __init__(self, klient: KlientOllama, indeks: IndeksHybrydowy, katalog_bazy: Path,
                 katalog_nauczone: Path, katalog_logow: Path, katalog_indeksu: Path | None = None,
                 top_k: int = 6, historia: int = 6, baza_meczow: BazaMeczow | None = None):
        self.baza_meczow = baza_meczow
        self.klient = klient
        self.indeks = indeks
        self.katalog_bazy = katalog_bazy
        self.katalog_indeksu = katalog_indeksu
        self.katalog_nauczone = katalog_nauczone
        self.katalog_logow = katalog_logow
        self.top_k = top_k
        self.historia = historia
        # Po udostępnieniu w internecie z bota korzysta kilka osób naraz (każda w osobnym wątku Streamlit).
        # Blokada pilnuje, żeby nikt nie przeszukiwał indeksu w chwili, gdy dopisuje się do niego nowy fakt.
        self._blokada = threading.RLock()

    # ================================================================ RAG
    @staticmethod
    def zapytanie_wyszukiwania(pytanie: str, rozmowa: list[dict]) -> str:
        """Pytania uzupełniające ("a ile razy wygrał RG?") nie mają podmiotu – doklejamy poprzednie pytanie.

        Doklejamy tylko wtedy, gdy pytanie wyraźnie nawiązuje do poprzedniego (partykuła „a”, zaimek)
        albo jest krótkie i nie zawiera żadnej nazwy własnej. „Ile tytułów zdobył Hurkacz?” ma własny
        podmiot, więc nie mieszamy go z poprzednim pytaniem o Federera.
        """
        poprzednie = [w["content"] for w in rozmowa if w["role"] == "user"]
        if not poprzednie:
            return pytanie
        bez_nazw = not re.search(r"\s[A-ZĄĆĘŁŃÓŚŹŻ]", pytanie.strip())
        if wyglada_na_uzupelniajace(pytanie) or (len(pytanie.split()) <= 8 and bez_nazw):
            return poprzednie[-1] + " " + pytanie
        return pytanie

    def wyszukaj(self, pytanie: str, rozmowa: list[dict] | None = None, k: int | None = None) -> list[Trafienie]:
        with self._blokada:
            return self.indeks.szukaj(self.zapytanie_wyszukiwania(pytanie, rozmowa or []), k=k or self.top_k)

    def kontekst_meczow(self, pytanie: str, rozmowa: list[dict]) -> WynikMeczow | None:
        if self.baza_meczow is None:
            return None
        poprzednie = [w["content"] for w in rozmowa if w["role"] == "user"]
        try:
            return self.baza_meczow.kontekst(pytanie, self._pytanie_odniesienia(poprzednie))
        except Exception:  # noqa: BLE001 – błąd bazy meczów nie może zablokować czatu
            return None

    def _pytanie_odniesienia(self, poprzednie: list[str]) -> str | None:
        """Do którego pytania nawiązuje rozmowa? Cofamy się przez łańcuch pytań uzupełniających:
        „Bilans Nadala z Federerem?” → „A w finałach?” → „A na trawie?” – odniesieniem jest pierwsze."""
        for p in reversed(poprzednie[-4:]):
            if self.baza_meczow.znajdz_zawodnikow(p) or not self.baza_meczow.bez_wlasnego_podmiotu(p):
                return p
        return poprzednie[-1] if poprzednie else None

    @staticmethod
    def zbuduj_kontekst(trafienia: list[Trafienie], mecze: WynikMeczow | None = None, opis_bazy: str = "") -> str:
        bloki = []
        if mecze is not None:
            bloki.append(f"[M] (źródło: baza meczów {opis_bazy})\n{mecze.tekst}")
        for nr, t in enumerate(trafienia, start=1):
            bloki.append(f"[{nr}] (źródło: {t.fragment.zrodlo})\n{t.fragment.tekst}")
        return "\n\n".join(bloki)

    def zbuduj_wiadomosci(self, pytanie: str, trafienia: list[Trafienie], rozmowa: list[dict], uzyj_rag: bool,
                          mecze: WynikMeczow | None = None) -> list[dict]:
        historia = rozmowa[-self.historia:] if self.historia else []
        if uzyj_rag:
            system = PROMPT_SYSTEMOWY_RAG.format(dzisiaj=dzisiaj_po_polsku())
            opis = self.baza_meczow.opis_zakresu() if self.baza_meczow is not None and mecze is not None else ""
            tresc = f"KONTEKST:\n{self.zbuduj_kontekst(trafienia, mecze, opis)}\n\nPYTANIE: {pytanie}"
            if mecze is not None and mecze.doprecyzowanie:  # pytanie uzupełniające bez nazwiska
                tresc += f"\n(Doprecyzowanie na podstawie poprzedniego pytania: {mecze.doprecyzowanie}.)"
            # Przypomnienie na końcu wiadomości: małe modele (np. Bielik 4.5B) przy długim kontekście
            # „zapominają” zasady z promptu systemowego i dopisują fakty z pamięci – często błędne.
            tresc += ("\n\nOdpowiedz wyłącznie na podstawie KONTEKSTU powyżej i po każdym fakcie podaj numer źródła "
                      "w nawiasie, np. [1] albo [M]. Nie dopisuj niczego, czego nie ma w kontekście.")
        else:
            system = PROMPT_SYSTEMOWY_BEZ_RAG.format(dzisiaj=dzisiaj_po_polsku())
            tresc = pytanie
        return [{"role": "system", "content": system}, *historia, {"role": "user", "content": tresc}]

    def zapytaj(self, pytanie: str, rozmowa: list[dict] | None = None, uzyj_rag: bool = True,
                top_k: int | None = None) -> Odpowiedz:
        """Zwraca obiekt z trafieniami i strumieniem tekstu (do wyświetlania na żywo).
        top_k – liczba fragmentów dla tej jednej rozmowy (suwak w interfejsie); domyślnie self.top_k."""
        rozmowa = rozmowa or []
        top_k = top_k or self.top_k
        trafienia = self.wyszukaj(pytanie, rozmowa, k=top_k) if uzyj_rag else []
        mecze = self.kontekst_meczow(pytanie, rozmowa) if uzyj_rag else None
        if mecze is not None:  # przy danych z bazy meczów wystarczy mniej fragmentów tekstu
            trafienia = trafienia[: max(3, top_k // 2)]
        wiadomosci = self.zbuduj_wiadomosci(pytanie, trafienia, rozmowa, uzyj_rag, mecze)
        odp = Odpowiedz(pytanie=pytanie, trafienia=trafienia, strumien=iter(()), mecze=mecze)

        def strumien() -> Iterator[str]:
            czesci = []
            for kawalek in self.klient.czat_strumien(wiadomosci):
                czesci.append(kawalek)
                yield kawalek
            odp.tekst = "".join(czesci)
            self._loguj("rozmowy.jsonl", {"czas": odp.czas, "pytanie": pytanie, "odpowiedz": odp.tekst, "rag": uzyj_rag,
                                          "zrodla": [t.fragment.id for t in trafienia],
                                          "baza_meczow": mecze.rodzaj if mecze else None})

        odp.strumien = strumien()
        return odp

    def zapytaj_tekst(self, pytanie: str, rozmowa: list[dict] | None = None, uzyj_rag: bool = True) -> Odpowiedz:
        """Wersja bez strumieniowania (np. do ewaluacji)."""
        odp = self.zapytaj(pytanie, rozmowa, uzyj_rag)
        for _ in odp.strumien:
            pass
        return odp

    # ================================================================ UCZENIE SIĘ
    def naucz(self, tekst: str, zrodlo: str = "użytkownik") -> Fragment:
        """Dodaje nowy fakt do bazy wiedzy: zapis do pliku (trwały) + do indeksu (od razu dostępny)."""
        tekst = tekst.strip()
        if len(tekst) < 10:
            raise ValueError("Fakt jest za krótki – napisz pełne zdanie.")
        teraz = datetime.now()
        self.katalog_nauczone.mkdir(parents=True, exist_ok=True)
        plik = self.katalog_nauczone / "nauczone.md"
        nowy_plik = not plik.exists()
        with open(plik, "a", encoding="utf-8") as f:
            if nowy_plik:
                f.write("# Wiedza dodana przez użytkowników\n\n")
            f.write(f"## Fakt dodany {teraz:%Y-%m-%d %H:%M} (źródło: {zrodlo})\n{tekst}\n\n")
        sciezka = plik.relative_to(self.katalog_bazy).as_posix()
        fragment = Fragment(
            id=f"{sciezka}#{teraz:%Y%m%d%H%M%S%f}",
            tekst=f"Wiedza dodana przez użytkownika ({teraz:%Y-%m-%d}, źródło: {zrodlo})\n{tekst}",
            zrodlo=sciezka,
            tytul=f"Fakt dodany {teraz:%Y-%m-%d}",
            meta={"nauczone": True},
        )
        with self._blokada:
            self.indeks.dodaj([fragment])
            self.zapisz_indeks()
        self._loguj("nauczone.jsonl", {"czas": teraz.isoformat(timespec="seconds"), "tekst": tekst, "zrodlo": zrodlo})
        return fragment

    def wgraj_dokument(self, sciezka: Path) -> int:
        """Dodaje do indeksu cały dokument (md/txt/pdf) leżący w katalogu bazy wiedzy. Zwraca liczbę fragmentów."""
        tresc = wczytaj_plik(sciezka)
        wzgledna = sciezka.resolve().relative_to(self.katalog_bazy.resolve()).as_posix()
        istniejace = {f.zrodlo for f in self.indeks.fragmenty}
        if wzgledna in istniejace:
            raise ValueError(f"Dokument {wzgledna} jest już w bazie wiedzy.")
        fragmenty = podziel_markdown(tresc, wzgledna)
        with self._blokada:
            self.indeks.dodaj(fragmenty)
            self.zapisz_indeks()
        return len(fragmenty)

    def ocena(self, pytanie: str, odpowiedz: str, dobra: bool, poprawka: str = "", ucz: bool = True) -> Fragment | None:
        """Informacja zwrotna. Zła ocena + poprawka = bot uczy się poprawnej odpowiedzi.
        ucz=False – tylko zapis oceny (w trybie publicznym poprawka gościa idzie najpierw do kolejki)."""
        self._loguj("oceny.jsonl", {"czas": datetime.now().isoformat(timespec="seconds"), "pytanie": pytanie,
                                    "odpowiedz": odpowiedz, "dobra": dobra, "poprawka": poprawka})
        if ucz and not dobra and poprawka.strip():
            return self.naucz(f"Pytanie: {pytanie}\nPoprawna odpowiedź: {poprawka.strip()}", zrodlo="korekta użytkownika")
        return None

    # ================================================================ pomocnicze
    def zapisz_indeks(self) -> None:
        if self.katalog_indeksu is not None:
            self.indeks.zapisz(self.katalog_indeksu)

    def _loguj(self, plik: str, wpis: dict) -> None:
        try:
            self.katalog_logow.mkdir(parents=True, exist_ok=True)
            with open(self.katalog_logow / plik, "a", encoding="utf-8") as f:
                f.write(json.dumps(wpis, ensure_ascii=False) + "\n")
        except OSError:
            pass  # logowanie nie może zatrzymać rozmowy
