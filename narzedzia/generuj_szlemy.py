"""Generuje pliki Markdown bazy wiedzy z tabeli finałów Wielkiego Szlema (dane_zrodlowe/finaly_wielkiego_szlema.csv).

Dlaczego generujemy tekst z tabeli, zamiast wrzucić CSV do bazy?
Model embeddingów i BM25 najlepiej działają na krótkich, pełnych zdaniach. Dlatego każdy finał
dostaje własny fragment ("Wimbledon 1987, singiel mężczyzn: wygrał Pat Cash..."), a dodatkowo
liczymy statystyki: ile tytułów ma każdy zawodnik, kto jest rekordzistą danego turnieju itd.
Liczby są wyliczane z danych, więc model nie musi ich "pamiętać" – to ogranicza halucynacje.

Użycie:  python -m narzedzia.generuj_szlemy
"""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path

KATALOG = Path(__file__).resolve().parent.parent
PLIK_CSV = KATALOG / "dane_zrodlowe" / "finaly_wielkiego_szlema.csv"
KATALOG_WYJ = KATALOG / "baza_wiedzy" / "wielki_szlem"

KRAJE = {
    "ARG": "Argentyna", "AUS": "Australia", "AUT": "Austria", "BEL": "Belgia", "BLR": "Białoruś",
    "BRA": "Brazylia", "CAN": "Kanada", "CHI": "Chile", "CHN": "Chiny", "CRO": "Chorwacja", "CYP": "Cypr",
    "CZE": "Czechy", "DEN": "Dania", "ECU": "Ekwador", "ESP": "Hiszpania", "FRA": "Francja",
    "FRG": "RFN (Niemcy Zachodnie)", "GBR": "Wielka Brytania", "GER": "Niemcy", "GRE": "Grecja",
    "ITA": "Włochy", "JPN": "Japonia", "KAZ": "Kazachstan", "LAT": "Łotwa", "NED": "Holandia",
    "NOR": "Norwegia", "NZL": "Nowa Zelandia", "PAR": "Paragwaj", "POL": "Polska", "ROU": "Rumunia",
    "RSA": "RPA", "RUS": "Rosja", "SRB": "Serbia", "SUI": "Szwajcaria", "SVK": "Słowacja",
    "SWE": "Szwecja", "TCH": "Czechosłowacja", "TUN": "Tunezja", "UKR": "Ukraina", "URS": "ZSRR",
    "USA": "USA", "YUG": "Jugosławia",
}

TURNIEJE = {
    "Australian Open": {"plik": "australian_open", "skrot": "AO",
                        "opis": "Australian Open (Otwarte Mistrzostwa Australii, AO, Melbourne)"},
    "Roland Garros": {"plik": "roland_garros", "skrot": "RG",
                      "opis": "Roland Garros (French Open, Otwarte Mistrzostwa Francji, RG, Paryż)"},
    "Wimbledon": {"plik": "wimbledon", "skrot": "W", "opis": "Wimbledon (Mistrzostwa Wimbledonu, Londyn)"},
    "US Open": {"plik": "us_open", "skrot": "USO", "opis": "US Open (Otwarte Mistrzostwa USA, Nowy Jork)"},
}
KOLEJNOSC = list(TURNIEJE)

# Polskie warianty pisowni – pomagają wyszukiwarce, gdy użytkownik pisze nazwisko "po polsku".
ALIASY = {
    "Novak Djokovic": "Novak Djoković (Dżoković)",
    "Ilie Năstase": "Ilie Năstase (Nastase)",
    "Björn Borg": "Björn Borg (Bjorn Borg)",
    "Yevgeny Kafelnikov": "Jewgienij Kafielnikow",
    "Marat Safin": "Marat Safin",
    "Daniil Medvedev": "Daniił Miedwiediew (Medvedev)",
    "Maria Sharapova": "Maria Szarapowa (Sharapova)",
    "Svetlana Kuznetsova": "Swietłana Kuzniecowa (Kuznetsova)",
    "Anastasia Myskina": "Anastasija Myskina",
    "Mirra Andreeva": "Mirra Andriejewa (Andreeva)",
    "Elena Rybakina": "Jelena Rybakina (Elena Rybakina)",
    "Aryna Sabalenka": "Aryna Sabalenka (Sabałenka)",
    "Victoria Azarenka": "Wiktoria Azarenka (Azaranka)",
    "Elena Dementieva": "Jelena Diemientjewa (Dementieva)",
    "Dinara Safina": "Dinara Safina",
    "Vera Zvonareva": "Wiera Zwonariowa (Zvonareva)",
    "Olga Morozova": "Olga Morozowa",
    "Natasha Zvereva": "Natalia Zwieriewa (Zvereva)",
    "Alexander Zverev": "Alexander Zverev (Aleksander Zwieriew)",
    "Andrei Medvedev": "Andrij Medwediew (Andrei Medvedev)",
    "Li Na": "Li Na",
    "Zheng Qinwen": "Zheng Qinwen",
}


def kraj(kod: str) -> str:
    return KRAJE.get(kod, kod)


def nazwa(osoba: str) -> str:
    return ALIASY.get(osoba, osoba)


def wczytaj() -> list[dict]:
    with open(PLIK_CSV, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def etykieta_edycji(w: dict) -> str:
    return f"{w['rok']} ({w['edycja']})" if w["edycja"] else w["rok"]


def zdanie_finalu(w: dict) -> str:
    k = w["plec"] == "kobiety"
    opis = TURNIEJE[w["turniej"]]["opis"]
    konk = "singiel kobiet (gra pojedyncza kobiet)" if k else "singiel mężczyzn (gra pojedyncza mężczyzn)"
    zw, fi = ("Zwyciężczyni", "Finalistka") if k else ("Zwycięzca", "Finalista")
    krecz = " (finał zakończył się kreczem, czyli poddaniem meczu przez finalistę)" if "krecz" in w["wynik"] else ""
    return (
        f"{w['turniej']} {etykieta_edycji(w)}, {konk}. Turniej: {opis}.\n"
        f"{zw}: {nazwa(w['zwyciezca'])} ({kraj(w['kraj_zwyciezcy'])}). "
        f"{fi}: {nazwa(w['finalista'])} ({kraj(w['kraj_finalisty'])}). "
        f"Wynik finału: {w['wynik']}.{krecz}\n"
        f"Kto wygrał {w['turniej']} {w['rok']} ({konk.split(' (')[0]})? {nazwa(w['zwyciezca'])}. "
        f"{'Przegrana' if k else 'Przegrany'} w finale: {nazwa(w['finalista'])}."
    )


def generuj_finaly(wiersze: list[dict]) -> dict[str, str]:
    pliki = {}
    for turniej, info in TURNIEJE.items():
        for plec, przyrostek, opis_plci in (("mężczyźni", "mezczyzni", "singiel mężczyzn"), ("kobiety", "kobiety", "singiel kobiet")):
            wybrane = [w for w in wiersze if w["turniej"] == turniej and w["plec"] == plec]
            linie = [f"# {turniej} – finały ({opis_plci}) w Erze Open", ""]
            for w in wybrane:
                linie += [f"## {turniej} {etykieta_edycji(w)} – {opis_plci}", zdanie_finalu(w), ""]
            pliki[f"finaly_{info['plik']}_{przyrostek}.md"] = "\n".join(linie)
    return pliki


def generuj_sezony(wiersze: list[dict]) -> str:
    po_roku: dict[str, list[dict]] = defaultdict(list)
    for w in wiersze:
        po_roku[w["rok"]].append(w)
    linie = ["# Mistrzowie Wielkiego Szlema rok po roku (Era Open)", "",
             "Zestawienie wszystkich zwycięzców turniejów wielkoszlemowych w grze pojedynczej w danym sezonie.", ""]
    for rok in sorted(po_roku, key=int):
        linie.append(f"## Sezon {rok} – mistrzowie Wielkiego Szlema")
        for plec, etyk in (("mężczyźni", "Mężczyźni"), ("kobiety", "Kobiety")):
            czesci = []
            for w in sorted(po_roku[rok], key=lambda x: (KOLEJNOSC.index(x["turniej"]), x["edycja"] != "styczeń")):
                if w["plec"] == plec:
                    czesci.append(f"{w['turniej']}{' (' + w['edycja'] + ')' if w['edycja'] else ''}: "
                                  f"{nazwa(w['zwyciezca'])} ({kraj(w['kraj_zwyciezcy'])})")
            linie.append(f"{etyk} w {rok}: " + "; ".join(czesci) + ".")
        brak = []
        if rok == "1986":
            brak.append("W 1986 roku nie rozegrano Australian Open (turniej przeniesiono z grudnia na styczeń 1987).")
        if rok == "2020":
            brak.append("W 2020 roku nie rozegrano Wimbledonu z powodu pandemii COVID-19; Roland Garros przeniesiono na wrzesień–październik.")
        if rok == "1977":
            brak.append("W 1977 roku Australian Open rozegrano dwukrotnie: w styczniu i w grudniu.")
        if rok == "1968":
            brak.append("Australian Open w 1968 roku był jeszcze turniejem amatorskim – Era Open w Melbourne zaczęła się w 1969 roku.")
        linie += brak + [""]
    return "\n".join(linie)


def odmien_turnieje(n: int) -> str:
    if n == 1:
        return "turniej wielkoszlemowy"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "turnieje wielkoszlemowe"
    return "turniejów wielkoszlemowych"


def lista_lat(tytuly: list[dict]) -> str:
    po_turnieju: dict[str, list[str]] = defaultdict(list)
    for w in tytuly:
        po_turnieju[w["turniej"]].append(etykieta_edycji(w))
    return "; ".join(f"{t} ×{len(po_turnieju[t])} ({', '.join(po_turnieju[t])})" for t in KOLEJNOSC if t in po_turnieju)


def generuj_zawodnikow(wiersze: list[dict]) -> str:
    tytuly: dict[str, list[dict]] = defaultdict(list)
    porazki: dict[str, list[dict]] = defaultdict(list)
    plec: dict[str, str] = {}
    kraj_os: dict[str, str] = {}
    for w in wiersze:
        tytuly[w["zwyciezca"]].append(w)
        porazki[w["finalista"]].append(w)
        plec[w["zwyciezca"]] = plec[w["finalista"]] = w["plec"]
        kraj_os.setdefault(w["zwyciezca"], w["kraj_zwyciezcy"])
        kraj_os[w["zwyciezca"]] = w["kraj_zwyciezcy"]  # ostatnie reprezentowane państwo
        kraj_os.setdefault(w["finalista"], w["kraj_finalisty"])

    linie = ["# Tytuły wielkoszlemowe zawodników w grze pojedynczej (Era Open, od 1968)", "",
             "UWAGA: liczby dotyczą wyłącznie Ery Open (od 1968 r.). Zawodnicy grający wcześniej "
             "(np. Rod Laver, Ken Rosewall, Margaret Court, Billie Jean King, Roy Emerson) mają łącznie więcej "
             "tytułów – patrz plik z rekordami.", ""]
    for osoba in sorted(tytuly, key=lambda o: (-len(tytuly[o]), o)):
        t, p = tytuly[osoba], porazki.get(osoba, [])
        k = plec[osoba] == "kobiety"
        lata = sorted({int(w["rok"]) for w in t})
        linie += [
            f"## {nazwa(osoba)} – tytuły wielkoszlemowe",
            f"{nazwa(osoba)} ({kraj(kraj_os[osoba])}, {'zawodniczka' if k else 'zawodnik'}) "
            f"{'wygrała' if k else 'wygrał'} w Erze Open {len(t)} {odmien_turnieje(len(t))} "
            f"w grze pojedynczej: {lista_lat(t)}.",
            f"Finały wielkoszlemowe: {len(t) + len(p)} (wygrane {len(t)}, przegrane {len(p)}). "
            f"Pierwszy tytuł: {lata[0]}, ostatni tytuł: {lata[-1]}.",
        ]
        if p:
            linie.append("Przegrane finały (w nawiasie mistrz/mistrzyni): " + "; ".join(
                f"{w['turniej']} {etykieta_edycji(w)} ({nazwa(w['zwyciezca'])})" for w in p) + ".")
        linie.append("")

    # finaliści bez tytułu (np. Agnieszka Radwańska, Maja Chwalińska)
    bez_tytulu = [o for o in porazki if o not in tytuly]
    linie += ["## Finaliści turniejów wielkoszlemowych bez tytułu (Era Open)",
              "Zawodnicy i zawodniczki, którzy grali w finale Wielkiego Szlema w singlu, ale nigdy go nie wygrali:"]
    for o in sorted(bez_tytulu):
        linie.append(f"- {nazwa(o)} ({kraj(kraj_os[o])}): " + "; ".join(
            f"{w['turniej']} {etykieta_edycji(w)} (przegrany finał, mistrz/mistrzyni: {nazwa(w['zwyciezca'])}, wynik {w['wynik']})" for w in porazki[o]))
    linie.append("")
    return "\n".join(linie)


def generuj_rankingi(wiersze: list[dict]) -> str:
    linie = ["# Rekordziści Wielkiego Szlema w Erze Open – rankingi wyliczone z wyników finałów", ""]
    for plec, etyk in (("mężczyźni", "mężczyzn"), ("kobiety", "kobiet")):
        licz = Counter(w["zwyciezca"] for w in wiersze if w["plec"] == plec)
        top = licz.most_common(20)
        linie += [f"## Najwięcej tytułów wielkoszlemowych w Erze Open – singiel {etyk}",
                  "Ranking (liczba tytułów od 1968 r.): " + "; ".join(f"{i}. {nazwa(o)} – {n}" for i, (o, n) in enumerate(top, 1)) + ".",
                  ""]
        for turniej in KOLEJNOSC:
            l2 = Counter(w["zwyciezca"] for w in wiersze if w["plec"] == plec and w["turniej"] == turniej)
            top2 = l2.most_common(5)
            linie += [f"## Rekordziści turnieju {turniej} w Erze Open – singiel {etyk}",
                      f"Najwięcej tytułów w {TURNIEJE[turniej]['opis']} (singiel {etyk}, od początku Ery Open): "
                      + "; ".join(f"{nazwa(o)} – {n}" for o, n in top2) + ".", ""]
        kraje = Counter(kraj(w["kraj_zwyciezcy"]) for w in wiersze if w["plec"] == plec)
        linie += [f"## Kraje z największą liczbą tytułów wielkoszlemowych – singiel {etyk} (Era Open)",
                  "; ".join(f"{k} – {n}" for k, n in kraje.most_common(15)) + ".", ""]
    polskie = [w for w in wiersze if "POL" in (w["kraj_zwyciezcy"], w["kraj_finalisty"])]
    linie += ["## Polacy i Polki w finałach Wielkiego Szlema w grze pojedynczej (Era Open)"]
    for w in polskie:
        polka_wygrala = w["kraj_zwyciezcy"] == "POL"
        linie.append(f"- {w['turniej']} {w['rok']}: " + (
            f"{nazwa(w['zwyciezca'])} WYGRAŁA turniej; rywalka w finale: {nazwa(w['finalista'])}; wynik {w['wynik']}." if polka_wygrala
            else f"{nazwa(w['finalista'])} przegrała finał; mistrzyni: {nazwa(w['zwyciezca'])}; wynik {w['wynik']}."))
    linie.append("")
    return "\n".join(linie)


def main() -> None:
    wiersze = wczytaj()
    KATALOG_WYJ.mkdir(parents=True, exist_ok=True)
    pliki = generuj_finaly(wiersze)
    pliki["sezony_rok_po_roku.md"] = generuj_sezony(wiersze)
    pliki["tytuly_zawodnikow.md"] = generuj_zawodnikow(wiersze)
    pliki["rekordzisci_i_statystyki.md"] = generuj_rankingi(wiersze)
    for nazwa_pliku, tresc in pliki.items():
        (KATALOG_WYJ / nazwa_pliku).write_text(tresc, encoding="utf-8")
    print(f"Wygenerowano {len(pliki)} plików z {len(wiersze)} finałów -> {KATALOG_WYJ}")


if __name__ == "__main__":
    main()
