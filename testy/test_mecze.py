"""Testy bazy meczów: import (Sackmann + tennis-data) z lokalnego serwera i zapytania w języku polskim."""
from __future__ import annotations

import functools
import http.server
import sys
import threading
from pathlib import Path

import pytest

KATALOG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KATALOG))

import config  # noqa: E402
from narzedzia import pobierz_mecze as pm  # noqa: E402
from silnik.mecze import BazaMeczow, turniej_druzynowy  # noqa: E402
from testy.dane_testowe import utworz  # noqa: E402


@pytest.fixture(scope="module")
def baza(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("mecze")
    serw = utworz(tmp / "serwer")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(serw))
    handler.log_message = lambda *a: None
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    mp = pytest.MonkeyPatch()
    mp.setattr(pm, "URL_LUSTRO", url)
    mp.setattr(pm, "URL_LUSTRO_HF", url + "/hf")
    mp.setattr(pm, "URL_TENNIS_DATA", url)
    mp.setattr(pm, "KATALOG_SACKMANN", tmp / "zrodla" / "sackmann")
    mp.setattr(pm, "KATALOG_TD", tmp / "zrodla" / "td")
    mp.setattr(config, "PLIK_BAZY_MECZOW", tmp / "mecze.sqlite")
    pm.pobierz_sackmann(["atp", "wta"], 1968, 2026, challengery=False, wymus=False)
    pm.pobierz_tennis_data(["atp", "wta"], 1968, 2026, wymus=False)
    sciezka = pm.zbuduj_baze(1968, 2026, ["atp", "wta"])
    yield BazaMeczow(sciezka, maks_meczow=10)
    mp.undo()
    httpd.shutdown()


def test_import_zakres(baza):
    z = baza.zakres()
    assert z["od"] == 1968 and z["do"] == 2026 and z["tury"] == ["ATP", "WTA"] and z["mecze"] == 468


def test_dopasowanie_nazwisk_tennis_data(baza):
    w = baza.mecze("Iga Świątek")
    assert any(m["rok"] == 2026 and m["zwyciezca"] == "Elena Rybakina" for m in w), "Swiatek I. -> Iga Świątek"
    assert baza.mecze("Jannik Sinner", "Alexander Zverev")[0]["turniej"] == "Australian Open"
    rg = baza.mecze(None, None, baza.wykryj_filtry("Roland Garros 2025 finał"))
    assert rg and all(m["turniej"] == "Roland Garros" for m in rg), "French Open -> Roland Garros"


@pytest.mark.parametrize("pytanie,oczekiwani", [
    ("Jaki jest bilans Nadala z Federerem?", ["Rafael Nadal", "Roger Federer"]),
    ("Mecze Djokovicia z Alcarazem", ["Novak Djokovic", "Carlos Alcaraz"]),
    ("Ile finałów zagrała Sereny Williams?", ["Serena Williams"]),
    ("Kariera Agnieszki Radwańskiej", ["Agnieszka Radwanska"]),
    ("Jak grał Hurkacz?", ["Hubert Hurkacz"]),
    ("Mecze Dżokovicia z Miedwiediewem", ["Novak Djokovic", "Daniil Medvedev"]),
    ("Kim jest Iga Świątek?", ["Iga Świątek"]),
    ("Jak działa tie-break?", []),
    ("Kto wygrał Puchar Davisa?", []),
])
def test_rozpoznawanie_zawodnikow(baza, pytanie, oczekiwani):
    assert [z.nazwa for z in baza.znajdz_zawodnikow(pytanie)] == oczekiwani


def test_filtry():
    f = BazaMeczow.wykryj_filtry("Finały Wimbledonu w latach 2010-2015 na trawie wśród kobiet")
    assert f.lata == (2010, 2015) and f.turniej == "Wimbledon" and f.rundy == ["F"] and f.nawierzchnia == "Grass" and f.tura == "WTA"
    f = BazaMeczow.wykryj_filtry("półfinał Roland Garros 2019")
    assert f.rundy == ["SF"] and f.turniej == "Roland Garros"


def test_h2h_i_kontekst(baza):
    w = baza.kontekst("Jaki jest bilans meczów Nadala z Federerem?")
    assert w.rodzaj == "h2h" and "6–4" in w.tekst and "W finałach: Rafael Nadal 6–3" in w.tekst
    w = baza.kontekst("Ile razy Nadal pokonał Federera w finale Roland Garros?")
    assert w.liczba_meczow == 4
    w = baza.kontekst("Hurkacz w 2025")
    assert w.rodzaj == "kariera" and "bilans 0–2" in w.tekst
    assert baza.kontekst("Kto wygrał Wimbledon 1987?").rodzaj == "turniej"
    assert baza.kontekst("Jak działa tie-break?") is None


def test_pytania_uzupelniajace(baza):
    w = baza.kontekst("A z Djokoviciem?", "Jaki jest bilans Nadala z Federerem?")
    assert w.zawodnicy == ["Rafael Nadal", "Novak Djokovic"]
    w = baza.kontekst("A na trawie?", "Jaki jest bilans Nadala z Federerem?")
    assert w.zawodnicy == ["Rafael Nadal", "Roger Federer"] and w.filtry.nawierzchnia == "Grass"


def test_samodzielne_pytanie_nie_laczy_sie_z_poprzednim(baza):
    # błąd z prawdziwej rozmowy: po pytaniu o Federera „Ile tytułów zdobył Hurkacz?” dawało bilans Hurkacz–Federer
    w = baza.kontekst("Ile tytułów zdobył Hurkacz?", "Ile break pointów obronił Federer w finale Wimbledonu 2019?")
    assert w.rodzaj == "kariera" and w.zawodnicy == ["Hubert Hurkacz"] and w.filtry.pusty()
    # rywal wskazany przyimkiem „z” – to nadal pytanie uzupełniające
    w = baza.kontekst("Ile razy wygrał z Federerem?", "Jaki jest bilans Nadala?")
    assert w.rodzaj == "h2h" and w.zawodnicy == ["Rafael Nadal", "Roger Federer"]
    assert "Rafael Nadal" in w.doprecyzowanie and w.tekst.startswith("Jak zrozumiano pytanie")
    assert baza.kontekst("Jaki jest bilans meczów Nadala z Federerem?").doprecyzowanie == ""
    # pytanie bez podmiotu dotyczy zawodnika z poprzedniego pytania
    w = baza.kontekst("Ile tytułów zdobył?", "Jaki jest bilans Hurkacza?")
    assert w.rodzaj == "kariera" and w.zawodnicy == ["Hubert Hurkacz"]
    # pytanie o turniej („kto wygrał…”) nie dziedziczy zawodnika
    assert baza.kontekst("Kto wygrał Wimbledon 1987?", "Jaki jest bilans Hurkacza?").rodzaj == "turniej"


def test_rozgrywki_druzynowe_to_nie_tytuly():
    assert turniej_druzynowy("United Cup", "A") and turniej_druzynowy("Davis Cup WG F: ESP vs ARG", "D")
    assert turniej_druzynowy("Laver Cup", "A") and turniej_druzynowy("Atp Cup", "A")
    assert not turniej_druzynowy("Wimbledon", "G") and not turniej_druzynowy("Grand Slam Cup", "A")


def test_odmiana_nazwisk():
    p = BazaMeczow._pasuje
    assert p("nadala", "nadal") and p("djokoviciem", "djokovic") and p("sabalenki", "sabalenka")
    assert p("radwanskiej", "radwanska") and p("swiatek", "swiatek") and not p("lee", "leeds")
    assert not p("ito", "itoh") and p("ito", "ito")


def test_kontrola_sensownosci_danych():
    assert pm.liczba_gemow("6-4 3-6 6-7(7) 7-6(3) 70-68") == 183
    w = {"wynik": "6-4 6-2", "minuty": 2475, "asy_zw": 72, "podwojne_zw": 72, "punkty_serw_zw": 70, "pierwszy_ok_zw": 40,
         "pierwszy_wyg_zw": 30, "drugi_wyg_zw": 15, "gemy_serw_zw": 9, "bp_obronione_zw": 1, "bp_bronione_zw": 2,
         "asy_prz": 1, "podwojne_prz": 2, "punkty_serw_prz": 60, "pierwszy_ok_prz": 35, "pierwszy_wyg_prz": 20,
         "drugi_wyg_prz": 10, "gemy_serw_prz": 9, "bp_obronione_prz": 3, "bp_bronione_prz": 6}
    pm.popraw_dane(w)
    assert w["minuty"] is None and w["asy_zw"] is None and w["punkty_serw_prz"] is None
    ok = {"wynik": "6-4 3-6 6-7(7) 7-6(3) 70-68", "minuty": 665, "asy_zw": 113, "podwojne_zw": 10, "punkty_serw_zw": 491}
    pm.popraw_dane(ok)
    assert ok["minuty"] == 665 and ok["asy_zw"] == 113


def test_wykrywanie_pytan_o_statystyki():
    assert BazaMeczow.wykryj_filtry("Ile asów zaserwował Hurkacz?").statystyki
    assert BazaMeczow.wykryj_filtry("Jaki był najdłuższy mecz?").rekord
    assert not BazaMeczow.wykryj_filtry("Kto wygrał Wimbledon 2019?").statystyki
