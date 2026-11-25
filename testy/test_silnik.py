"""Testy jednostkowe silnika (bez Ollamy).  Uruchom:  python -m pytest testy -q"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

KATALOG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KATALOG))

from ewaluacja import zawiera_odpowiedz  # noqa: E402
from narzedzia.pobierz_wikipedia import na_markdown, przetworz_odpowiedz  # noqa: E402
from silnik import TenisBot, wczytaj_fragmenty_bazy  # noqa: E402
from silnik.indeks import BM25, IndeksHybrydowy  # noqa: E402
from silnik.tekst import Fragment, bez_ogonkow, podziel_markdown, tokeny  # noqa: E402
from testy.falszywa_ollama import osadz  # noqa: E402


def falszywy_embedder(teksty):
    return [osadz(t) for t in teksty]


class FalszywyKlient:
    model_llm = "atrapa"

    def embed(self, teksty):
        return falszywy_embedder(teksty)

    def czat_strumien(self, wiadomosci, model=None):
        yield "odpowiedź "
        yield "testowa"


# ------------------------------------------------------------------ tekst
def test_bez_ogonkow():
    assert bez_ogonkow("Świątek Djoković Łódź Năstase") == "Swiatek Djokovic Lodz Nastase"


def test_tokeny_rdzenie_i_liczby():
    t = tokeny("Kto wygrał Wimbledon w 1987? Wimbledonie, Nadala")
    assert "1987" in t and t.count("wimbl") == 2 and "nadal" in t and "kto" not in t


def test_podziel_markdown_naglowki():
    md = "# Tytuł\n\n## Sekcja A\nTreść A.\n\n## Sekcja B\nTreść B."
    fr = podziel_markdown(md, "plik.md")
    assert [f.tytul for f in fr] == ["Tytuł – Sekcja A", "Tytuł – Sekcja B"]
    assert fr[0].tekst.startswith("Tytuł – Sekcja A\n") and "Treść A." in fr[0].tekst


def test_podziel_dluga_sekcje():
    akapity = "\n\n".join(f"Akapit numer {i}. " + "słowo " * 60 for i in range(10))
    fr = podziel_markdown(f"# T\n\n## S\n{akapity}", "x.md", max_znakow=500, zakladka=50)
    assert len(fr) > 3 and all(len(f.tekst) < 700 for f in fr)


# ------------------------------------------------------------------ indeks
def test_bm25_ranking():
    bm = BM25([tokeny("Nadal wygrał Roland Garros"), tokeny("Federer wygrał Wimbledon"), tokeny("zasady tie-breaka")])
    oceny = bm.wyniki(tokeny("Kto wygrał Wimbledon?"))
    assert oceny.argmax() == 1


def test_indeks_zapis_wczytanie_dodawanie(tmp_path):
    fr = [Fragment(id=f"a#{i}", tekst=t, zrodlo="a.md", tytul="a") for i, t in
          enumerate(["Iga Świątek wygrała Wimbledon 2025", "Pat Cash wygrał Wimbledon 1987", "Siatka ma 0,914 m"])]
    idx = IndeksHybrydowy(falszywy_embedder, "atrapa")
    idx.zbuduj(fr)
    assert idx.szukaj("Wimbledon 1987", k=1)[0].fragment.id == "a#1"
    idx.zapisz(tmp_path)
    idx2 = IndeksHybrydowy.wczytaj(tmp_path, falszywy_embedder, "atrapa")
    assert len(idx2.fragmenty) == 3 and idx2.wektory.shape == idx.wektory.shape
    idx2.dodaj([Fragment(id="b#0", tekst="Zverev wygrał US Open 2026", zrodlo="b.md", tytul="b")])
    assert idx2.szukaj("US Open 2026 Zverev", k=1)[0].fragment.id == "b#0"
    with pytest.raises(ValueError):
        IndeksHybrydowy.wczytaj(tmp_path, falszywy_embedder, "inny-model")


# ------------------------------------------------------------------ bot i uczenie się
def test_bot_uczy_sie(tmp_path):
    baza = tmp_path / "baza"
    baza.mkdir()
    idx = IndeksHybrydowy(falszywy_embedder, "atrapa")
    idx.zbuduj([Fragment(id="x#0", tekst="Zasady tenisa: gem, set, mecz.", zrodlo="x.md", tytul="x")])
    bot = TenisBot(FalszywyKlient(), idx, baza, baza / "nauczone", tmp_path / "logi", tmp_path / "indeks", top_k=3)
    bot.naucz("ATP Finals 2026 wygrał Testowy Zawodnik z Atrapii.", zrodlo="test")
    assert (baza / "nauczone" / "nauczone.md").read_text(encoding="utf-8").count("Testowy Zawodnik") == 1
    assert (tmp_path / "indeks" / "fragmenty.json").exists()
    trafienia = bot.wyszukaj("Kto wygrał ATP Finals 2026?")
    assert "Testowy Zawodnik" in trafienia[0].fragment.tekst
    odp = bot.zapytaj_tekst("Kto wygrał ATP Finals 2026?")
    assert odp.tekst == "odpowiedź testowa"
    assert (tmp_path / "logi" / "rozmowy.jsonl").exists()
    # zła ocena z poprawką -> nowy fakt
    bot.ocena("Ile lat ma atrapa?", "nie wiem", dobra=False, poprawka="Atrapa ma 3 lata.")
    assert "Atrapa ma 3 lata." in (baza / "nauczone" / "nauczone.md").read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        bot.naucz("za krótko")


def test_zapytanie_uzupelniajace():
    rozmowa = [{"role": "user", "content": "Kim jest Rafael Nadal?"}, {"role": "assistant", "content": "..."}]
    assert "Nadal" in TenisBot.zapytanie_wyszukiwania("A ile razy wygrał Roland Garros?", rozmowa)
    assert "Nadal" not in TenisBot.zapytanie_wyszukiwania("Ile tytułów zdobył Hurkacz?", rozmowa)


def test_prompt_zawiera_kontekst_i_numery():
    idx = IndeksHybrydowy(falszywy_embedder, "atrapa")
    idx.zbuduj([Fragment(id="x#0", tekst="Fakt testowy", zrodlo="x.md", tytul="x")])
    bot = TenisBot(FalszywyKlient(), idx, Path("."), Path("."), Path("."))
    w = bot.zbuduj_wiadomosci("pytanie?", idx.szukaj("Fakt"), [], uzyj_rag=True)
    assert w[0]["role"] == "system" and "KONTEKST" in w[-1]["content"] and "[1]" in w[-1]["content"]


# ------------------------------------------------------------------ dane i baza wiedzy
def test_dane_wielkiego_szlema_spojne():
    with open(KATALOG / "dane_zrodlowe" / "finaly_wielkiego_szlema.csv", encoding="utf-8") as f:
        wiersze = list(csv.DictReader(f))
    tytuly = Counter(w["zwyciezca"] for w in wiersze)
    assert tytuly["Novak Djokovic"] == 24 and tytuly["Rafael Nadal"] == 22 and tytuly["Roger Federer"] == 20
    assert tytuly["Serena Williams"] == 23 and tytuly["Steffi Graf"] == 22 and tytuly["Iga Świątek"] == 6
    lata_w = {w["rok"] for w in wiersze if w["turniej"] == "Wimbledon"}
    assert "2020" not in lata_w and "2026" in lata_w
    assert len(wiersze) == 468


def test_baza_wiedzy_pokrywa_pytania_testowe():
    """Czy dla (prawie) każdego pytania testowego wyszukiwarka znajduje fragment z odpowiedzią?"""
    fragmenty = wczytaj_fragmenty_bazy(KATALOG / "baza_wiedzy")
    idx = IndeksHybrydowy(falszywy_embedder, "atrapa")
    idx.zbuduj(fragmenty)
    pytania = json.loads((KATALOG / "testy" / "pytania_testowe.json").read_text(encoding="utf-8"))
    trafione = 0
    for p in pytania:
        kontekst = "\n".join(t.fragment.tekst for t in idx.szukaj(p["pytanie"], k=6))
        trafione += zawiera_odpowiedz(kontekst, p["oczekiwane"])
    assert trafione / len(pytania) >= 0.85, f"recall@6 = {trafione}/{len(pytania)}"


# ------------------------------------------------------------------ narzędzia
def test_wikipedia_parsowanie():
    dane = {"query": {"pages": [{"title": "Tenis", "extract": "Wstęp.\n== Historia ==\nOpis.\n== Przypisy ==\n[1]"}]}}
    tytul, tekst = przetworz_odpowiedz(dane)
    md = na_markdown(tytul, tekst)
    assert "## Tenis – Historia" in md and "Przypisy" not in md
    assert przetworz_odpowiedz({"query": {"pages": [{"title": "X", "missing": True}]}}) is None


def test_zawiera_odpowiedz():
    assert zawiera_odpowiedz("Wygrał Novak Djoković", [["djokovic"]])
    assert not zawiera_odpowiedz("Wygrał Nadal", [["djokovic"]])
    assert zawiera_odpowiedz("Andriejewa pokonała Chwalińską", [["andriejew"], ["chwalinsk"]])


def test_przebudowa_liczy_tylko_zmienione_fragmenty(tmp_path):
    from silnik.indeks import IndeksHybrydowy
    from silnik.tekst import Fragment

    policzone: list[str] = []

    def embedder(teksty):
        policzone.extend(teksty)
        return [[float(len(t)), 1.0, 0.5] for t in teksty]

    fr = [Fragment(id=f"a#{i}", zrodlo="a.md", tytul="t", tekst=f"tekst numer {i}") for i in range(5)]
    idx = IndeksHybrydowy(embedder, "model-x")
    assert idx.zbuduj(fr) == 5
    idx.zapisz(tmp_path)
    pamiec = IndeksHybrydowy.pamiec_z_katalogu(tmp_path, "model-x")
    assert len(pamiec) == 5 and IndeksHybrydowy.pamiec_z_katalogu(tmp_path, "inny-model") == {}
    policzone.clear()
    zmienione = fr[:4] + [Fragment(id="a#9", zrodlo="a.md", tytul="t", tekst="zupełnie nowy fragment")]
    idx2 = IndeksHybrydowy(embedder, "model-x")
    assert idx2.zbuduj(zmienione, pamiec=pamiec) == 1 and policzone == ["zupełnie nowy fragment"]
    assert idx2.wektory.shape == (5, 3)
    assert abs(idx2.wektory[0] - idx.wektory[0]).max() < 1e-6


def test_kolejka_faktow(tmp_path):
    from silnik.kolejka import KolejkaFaktow

    k = KolejkaFaktow(tmp_path / "kolejka.json")
    with pytest.raises(ValueError):
        k.dodaj("za krótko")
    w = k.dodaj("Turniej ATP Finals 2026 rozegrano w Turynie.", "gość")
    k.dodaj("Pytanie: X\nPoprawna odpowiedź: Y – dłuższy tekst.", "korekta gościa", rodzaj="poprawka")
    assert [x["rodzaj"] for x in k.lista()] == ["fakt", "poprawka"]
    assert k.wyjmij(w["id"])["tekst"].startswith("Turniej") and len(k.lista()) == 1
    assert k.wyjmij("nie-ma-takiego") is None


def test_klient_api_zgodny_z_openai():
    """Wersja w chmurze: czat ze strumieniowaniem, embeddingi z ponowieniem po 429 i czytelny błąd złego klucza."""
    import threading
    from http.server import ThreadingHTTPServer

    from silnik import BladOllamy, KlientAPI
    from testy import falszywe_api

    falszywe_api.STAN["embeddingi"] = 0
    serwer = ThreadingHTTPServer(("127.0.0.1", 0), falszywe_api.Obsluga)
    threading.Thread(target=serwer.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{serwer.server_address[1]}/v1"
    try:
        klient = KlientAPI(url, "klucz-testowy", "mistral-small-latest", "mistral-embed")
        wektory = klient.embed(["Wimbledon to turniej na trawie", "Roland Garros na mączce"])  # 1. próba: 429
        assert len(wektory) == 2 and len(wektory[0]) == 256
        odp = klient.czat([{"role": "user", "content": "KONTEKST:\n[1] Zasady\nTie-break gra się do 7.\n\nPYTANIE: ?"}])
        assert "Tie-break" in odp
        assert klient.sprawdz() == []
        zly = KlientAPI(url, "zly-klucz", "mistral-small-latest", "mistral-embed")
        assert "Klucz API" in zly.sprawdz()[0]
        with pytest.raises(BladOllamy, match="Klucz API"):
            zly.czat([{"role": "user", "content": "test"}])
    finally:
        serwer.shutdown()


def test_indeks_bez_embeddingow_dziala_na_bm25():
    from silnik.indeks import IndeksHybrydowy
    from silnik.tekst import Fragment

    fr = [Fragment(id="a", zrodlo="a.md", tytul="t", tekst="Tie-break rozgrywa się przy stanie 6:6."),
          Fragment(id="b", zrodlo="a.md", tytul="t", tekst="Mączka to nawierzchnia ziemna.")]
    idx = IndeksHybrydowy(None)
    idx.zbuduj(fr)
    assert idx.szukaj("kiedy gra się tie-break", k=1)[0].fragment.id == "a"
