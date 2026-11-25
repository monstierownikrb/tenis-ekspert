"""Pobiera PEŁNĄ historię meczów singlowych ATP i WTA i buduje lokalną bazę SQLite: dane/mecze.sqlite

Źródła danych:
  1) Dane Jeffa Sackmanna / Tennis Abstract (pliki CSV, jeden na sezon; licencja CC BY-NC-SA 4.0 – wolno używać
     niekomercyjnie z podaniem autora). Oryginalne repozytoria JeffSackmann/tennis_atp i tennis_wta zniknęły
     z GitHuba (jesień 2026), więc pobieramy je z archiwalnej kopii: github.com/Aneeshers/tennis-sackmann-archive
     (zapasowo: huggingface.co/datasets/Aneeshers/tennis-sackmann-archive). Kopia obejmuje lata 1968 – 2026
     (sezon 2026 do Roland Garros).
  2) Opcjonalnie: tennis-data.co.uk – pliki Excel, którymi skrypt próbuje uzupełnić mecze rozegrane PO ostatniej
     dacie w danych Sackmanna. Nazwiska są tam zapisane jako "Sinner J." – skrypt dopasowuje je do pełnych nazw.

Użycie (z głównego folderu projektu, w aktywnym .venv):
  python -m narzedzia.pobierz_mecze                    # ATP + WTA, 1968 – dziś (ok. 100 MB, kilka minut)
  python -m narzedzia.pobierz_mecze --od 2000          # tylko od 2000 r.
  python -m narzedzia.pobierz_mecze --tury atp         # tylko mężczyźni
  python -m narzedzia.pobierz_mecze --challengery      # + challengery i kwalifikacje ATP (dużo więcej meczów)
  python -m narzedzia.pobierz_mecze --bez-pobierania   # zbuduj bazę z plików już pobranych
  python -m narzedzia.pobierz_mecze --odswiez          # pobierz wszystko ponownie

Bieżący sezon warto odświeżać co jakiś czas (np. raz w tygodniu) – wystarczy uruchomić skrypt jeszcze raz.
Jeśli pobieranie się nie uda (np. blokada sieci na uczelni), pobierz pliki ręcznie i wrzuć do:
  dane_zrodlowe/mecze/sackmann/      (np. atp_matches_2024.csv, wta_matches_2024.csv – z folderów atp/ i wta/ kopii)
  dane_zrodlowe/mecze/tennis_data/   (np. atp_2025.xlsx, wta_2025.xlsx)
a potem uruchom z opcją --bez-pobierania.
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from silnik.mecze import norm  # noqa: E402

# Adresy można nadpisać zmiennymi środowiskowymi (przydaje się w testach i przy innych kopiach danych).
URL_LUSTRO = os.environ.get("URL_LUSTRO", "https://raw.githubusercontent.com/Aneeshers/tennis-sackmann-archive/main")
URL_LUSTRO_HF = os.environ.get("URL_LUSTRO_HF", "https://huggingface.co/datasets/Aneeshers/tennis-sackmann-archive/resolve/main")
URL_TENNIS_DATA = os.environ.get("URL_TENNIS_DATA", "http://www.tennis-data.co.uk")
NAGLOWKI = {"User-Agent": "TenisowyEkspert/1.0 (projekt studencki)"}

KATALOG_SACKMANN = config.KATALOG_MECZOW_ZRODLA / "sackmann"
KATALOG_TD = config.KATALOG_MECZOW_ZRODLA / "tennis_data"

KOLUMNY = [
    "tura", "data", "rok", "turniej", "turniej_norm", "poziom", "ranga", "nawierzchnia", "runda",
    "zwyciezca", "zwyciezca_kraj", "przegrany", "przegrany_kraj", "wynik", "do_ilu_setow", "minuty",
    "ranking_zw", "ranking_prz", "asy_zw", "asy_prz", "podwojne_zw", "podwojne_prz", "zrodlo", "kolejnosc",
    # statystyki serwisu (Sackmann: ATP od 1991, WTA od ok. 2007); _zw = zwycięzca, _prz = przegrany
    "punkty_serw_zw", "pierwszy_ok_zw", "pierwszy_wyg_zw", "drugi_wyg_zw", "gemy_serw_zw", "bp_obronione_zw", "bp_bronione_zw",
    "punkty_serw_prz", "pierwszy_ok_prz", "pierwszy_wyg_prz", "drugi_wyg_prz", "gemy_serw_prz", "bp_obronione_prz", "bp_bronione_prz",
]
# kolumna Sackmanna -> nasza kolumna (dla zwycięzcy "w_", dla przegranego "l_")
STATYSTYKI_SACKMANN = {"svpt": "punkty_serw", "1stIn": "pierwszy_ok", "1stWon": "pierwszy_wyg", "2ndWon": "drugi_wyg",
                       "SvGms": "gemy_serw", "bpSaved": "bp_obronione", "bpFaced": "bp_bronione"}

RANGI_SACKMANN = {
    "G": "Wielki Szlem", "M": "Masters 1000", "A": "turniej ATP", "F": "turniej finałowy", "D": "Puchar Davisa / BJK Cup",
    "O": "igrzyska olimpijskie", "C": "Challenger", "S": "ITF", "PM": "WTA Premier Mandatory", "P": "WTA Premier",
    "I": "WTA International", "W": "WTA 1000", "T1": "WTA Tier I", "T2": "WTA Tier II", "T3": "WTA Tier III",
    "T4": "WTA Tier IV", "T5": "WTA Tier V", "E": "inny", "J": "juniorski",
}
# tennis-data.co.uk: kolumna Series (ATP) / Tier (WTA) -> (kod poziomu, ranga)
POZIOMY_TD = {
    "grand slam": ("G", "Wielki Szlem"), "masters 1000": ("M", "Masters 1000"), "masters": ("M", "Masters 1000"),
    "atp500": ("A", "ATP 500"), "atp250": ("A", "ATP 250"), "international gold": ("A", "ATP 500"),
    "international": ("A", "ATP 250"), "masters cup": ("F", "turniej finałowy"), "atp finals": ("F", "turniej finałowy"),
    "wta1000": ("W", "WTA 1000"), "wta 1000": ("W", "WTA 1000"), "wta500": ("P", "WTA 500"), "wta 500": ("P", "WTA 500"),
    "wta250": ("I", "WTA 250"), "wta 250": ("I", "WTA 250"), "tour championships": ("F", "turniej finałowy"),
    "wta finals": ("F", "turniej finałowy"), "premier": ("P", "WTA Premier"), "premier mandatory": ("PM", "WTA Premier Mandatory"),
    "international ": ("I", "WTA International"),
}
RUNDY_TD = {"the final": "F", "final": "F", "semifinals": "SF", "quarterfinals": "QF", "round robin": "RR",
            "1st round": "1R", "2nd round": "2R", "3rd round": "3R", "4th round": "4R", "bronze medal": "BR"}
NAZWY_SZLEMOW_TD = {"french open": "Roland Garros", "australian open": "Australian Open", "wimbledon": "Wimbledon",
                    "us open": "US Open"}


# ============================================================================= pobieranie
def pobierz_plik(url: str, cel: Path, wymus: bool = False) -> str:
    """Zwraca: 'pobrano' | 'jest' | 'brak' (404) | 'blad: ...'."""
    if cel.exists() and cel.stat().st_size > 0 and not wymus:
        return "jest"
    for proba in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=NAGLOWKI), timeout=60) as odp:
                dane = odp.read()
            cel.parent.mkdir(parents=True, exist_ok=True)
            tymczasowy = cel.with_suffix(cel.suffix + ".tmp")
            tymczasowy.write_bytes(dane)
            tymczasowy.replace(cel)
            return "pobrano"
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return "brak"
            blad = f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            blad = str(e)
        time.sleep(1 + proba)
    return f"blad: {blad}"


def pobierz_sackmann(tury: list[str], od: int, do: int, challengery: bool, wymus: bool) -> None:
    biezacy = date.today().year
    for tura in tury:
        for rok in range(od, do + 1):
            pliki = [f"{tura}_matches_{rok}.csv"]
            if challengery and tura == "atp":
                pliki.append(f"atp_matches_qual_chall_{rok}.csv")
            for nazwa in pliki:
                stan = "brak"
                # bieżący sezon pobieramy zawsze od nowa – kopia może zostać zaktualizowana
                for baza in (URL_LUSTRO, URL_LUSTRO_HF):
                    stan = pobierz_plik(f"{baza}/{tura}/{nazwa}", KATALOG_SACKMANN / nazwa, wymus or rok == biezacy)
                    if stan in ("pobrano", "jest"):
                        break
                if stan == "pobrano":
                    print(f"  {nazwa}: pobrano      ", end="\r", flush=True)
                elif stan != "jest":
                    print(f"  {nazwa}: {stan}        ")
        print(f"  {tura.upper()}: gotowe{' ' * 30}")


def ostatni_rok_sackmanna(tura: str) -> int | None:
    lata = [_int(p.stem.split("_")[-1]) for p in KATALOG_SACKMANN.glob(f"{tura}_matches_*.csv")
            if p.stem.split("_")[-1].isdigit()]
    return max(lata) if lata else None


def pobierz_tennis_data(tury: list[str], od: int, do: int, wymus: bool) -> None:
    """Uzupełnienie (opcjonalne): sezony, w których dane Sackmanna mogą być niepełne."""
    biezacy = date.today().year
    for tura in tury:
        start = max(od, ostatni_rok_sackmanna(tura) or od)
        for rok in range(start, do + 1):
            katalog = f"{rok}w" if tura == "wta" else f"{rok}"
            cel = KATALOG_TD / f"{tura}_{rok}.xlsx"
            stan = pobierz_plik(f"{URL_TENNIS_DATA}/{katalog}/{rok}.xlsx", cel, wymus or rok == biezacy)
            opis = {"brak": "niedostępne (pomijam – to tylko uzupełnienie)"}.get(stan, stan)
            print(f"  tennis-data {tura.upper()} {rok}: {opis}")


# ============================================================================= wczytywanie
def _int(x) -> int | None:
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return None


def czytaj_csv(sciezka: Path) -> list[dict]:
    surowe = sciezka.read_bytes()
    try:
        tekst = surowe.decode("utf-8-sig")
    except UnicodeDecodeError:
        tekst = surowe.decode("latin-1")
    return list(csv.DictReader(io.StringIO(tekst)))


def liczba_gemow(wynik: str) -> int:
    """Suma gemów z wyniku "6-4 7-6(5) 70-68" (bez punktów tie-breaka w nawiasach)."""
    bez_nawiasow = re.sub(r"\(.*?\)|\[.*?\]", "", wynik or "")
    return sum(int(x) for x in re.findall(r"\d+", bez_nawiasow))


def popraw_dane(w: dict) -> dict:
    """Kontrola sensowności – źródło zawiera pojedyncze błędne wpisy (np. mecz 6-4 6-2 trwający "41 godzin")."""
    gemy = liczba_gemow(w["wynik"])
    if w["minuty"] is not None and (w["minuty"] > gemy * 10 + 60 or w["minuty"] < max(gemy, 1)):
        w["minuty"] = None
    for s in ("zw", "prz"):
        sv, p1 = w.get(f"punkty_serw_{s}"), w.get(f"pierwszy_ok_{s}")
        if sv is None:
            continue
        bledne = (
            (w.get(f"asy_{s}") or 0) + (w.get(f"podwojne_{s}") or 0) > sv
            or (p1 or 0) > sv
            or (w.get(f"pierwszy_wyg_{s}") or 0) > (p1 or 0)
            or (w.get(f"drugi_wyg_{s}") or 0) > sv - (p1 or 0)
            or (w.get(f"bp_obronione_{s}") or 0) > (w.get(f"bp_bronione_{s}") or 0)
            or sv > max(gemy, 1) * 15
        )
        if bledne:  # odrzucamy statystyki całego meczu (obu zawodników), wynik zostaje
            for pole in ("asy", "podwojne", *STATYSTYKI_SACKMANN.values()):
                w[f"{pole}_zw"] = w[f"{pole}_prz"] = None
            break
    return w


NAZWY_TURNIEJOW = {"us open": "US Open", "Us Open": "US Open"}


def wiersze_sackmann(sciezka: Path) -> list[dict]:
    tura = "WTA" if sciezka.name.startswith("wta") else "ATP"
    wynik = []
    for r in czytaj_csv(sciezka):
        d = (r.get("tourney_date") or "").strip()
        if len(d) < 8 or not r.get("winner_name") or not r.get("loser_name"):
            continue
        poziom = (r.get("tourney_level") or "").strip()
        staty = {}
        for zrodlo, cel in STATYSTYKI_SACKMANN.items():
            staty[f"{cel}_zw"] = _int(r.get(f"w_{zrodlo}"))
            staty[f"{cel}_prz"] = _int(r.get(f"l_{zrodlo}"))
        wynik.append({**staty,
            "tura": tura, "data": f"{d[:4]}-{d[4:6]}-{d[6:8]}", "rok": int(d[:4]),
            "turniej": NAZWY_TURNIEJOW.get(r.get("tourney_name", "").strip(), r.get("tourney_name", "").strip()),
            "poziom": poziom, "ranga": RANGI_SACKMANN.get(poziom, poziom),
            "nawierzchnia": (r.get("surface") or "").strip() or None, "runda": (r.get("round") or "").strip(),
            "zwyciezca": r["winner_name"].strip(), "zwyciezca_kraj": (r.get("winner_ioc") or "").strip(),
            "przegrany": r["loser_name"].strip(), "przegrany_kraj": (r.get("loser_ioc") or "").strip(),
            "wynik": (r.get("score") or "").strip(), "do_ilu_setow": _int(r.get("best_of")), "minuty": _int(r.get("minutes")),
            "ranking_zw": _int(r.get("winner_rank")), "ranking_prz": _int(r.get("loser_rank")),
            "asy_zw": _int(r.get("w_ace")), "asy_prz": _int(r.get("l_ace")),
            "podwojne_zw": _int(r.get("w_df")), "podwojne_prz": _int(r.get("l_df")),
            "zrodlo": "Sackmann", "kolejnosc": _int(r.get("match_num")) or 0,
        })
    return wynik


class DopasowanieNazwisk:
    """Zamienia zapis tennis-data ("Auger-Aliassime F.") na pełną nazwę z danych Sackmanna ("Felix Auger Aliassime")."""

    def __init__(self, pelne_nazwy: dict[str, tuple[int, int]]):  # nazwa -> (ostatni_rok, liczba_meczow)
        self.indeks: dict[str, list[tuple[str, str, tuple[int, int]]]] = defaultdict(list)
        for nazwa, info in pelne_nazwy.items():
            n = norm(nazwa)
            if " " in n:
                self.indeks[n.split()[-1]].append((nazwa, n, info))
        self.pamiec: dict[str, str] = {}

    def __call__(self, zapis: str) -> str:
        zapis = (zapis or "").strip()
        if zapis in self.pamiec:
            return self.pamiec[zapis]
        czlony = zapis.split()
        wynik = zapis
        if len(czlony) >= 2 and czlony[-1].endswith("."):
            nazwisko = norm(" ".join(czlony[:-1]))
            inicjal = norm(czlony[-1])[:1]
            kandydaci = [
                (nazwa, info) for nazwa, n, info in self.indeks.get(nazwisko.split()[-1] if nazwisko else "", [])
                if n.endswith(" " + nazwisko) and n[:1] == inicjal
            ]
            if kandydaci:
                wynik = max(kandydaci, key=lambda k: k[1])[0]
            else:  # nowy zawodnik, którego nie ma u Sackmanna: "Sinner J." -> "J. Sinner"
                wynik = f"{czlony[-1]} {' '.join(czlony[:-1])}"
        self.pamiec[zapis] = wynik
        return wynik


def wiersze_tennis_data(sciezka: Path, dopasuj: DopasowanieNazwisk) -> list[dict]:
    from openpyxl import load_workbook

    tura = "WTA" if sciezka.name.startswith("wta") else "ATP"
    ks = load_workbook(sciezka, read_only=True, data_only=True)
    arkusz = ks.worksheets[0]
    wiersze = arkusz.iter_rows(values_only=True)
    naglowek = [str(x).strip() if x is not None else "" for x in next(wiersze)]
    idx = {n: i for i, n in enumerate(naglowek)}

    def pole(r, nazwa):
        i = idx.get(nazwa)
        return r[i] if i is not None and i < len(r) else None

    wynik = []
    for nr, r in enumerate(wiersze):
        zw, prz = pole(r, "Winner"), pole(r, "Loser")
        d = pole(r, "Date")
        if not zw or not prz or d is None:
            continue
        if isinstance(d, (datetime, date)):
            data_str = d.strftime("%Y-%m-%d")
        else:
            try:
                data_str = datetime.strptime(str(d)[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
            except ValueError:
                try:
                    data_str = datetime.strptime(str(d)[:10], "%d/%m/%Y").strftime("%Y-%m-%d")
                except ValueError:
                    continue
        seria = str(pole(r, "Series") or pole(r, "Tier") or "").strip()
        poziom, ranga = POZIOMY_TD.get(seria.lower(), ("A" if tura == "ATP" else "I", seria or "inny"))
        turniej = str(pole(r, "Tournament") or "").strip()
        turniej = NAZWY_SZLEMOW_TD.get(turniej.lower(), turniej)
        sety = []
        for s in range(1, 6):
            a, b = _int(pole(r, f"W{s}")), _int(pole(r, f"L{s}"))
            if a is None or b is None:
                break
            sety.append(f"{a}-{b}")
        komentarz = str(pole(r, "Comment") or "").strip().lower()
        wynik_str = " ".join(sety)
        if komentarz.startswith("retired"):
            wynik_str += " RET"
        elif komentarz.startswith("walkover"):
            wynik_str = "W/O"
        nawierzchnia = str(pole(r, "Surface") or "").strip().capitalize() or None
        runda = RUNDY_TD.get(str(pole(r, "Round") or "").strip().lower(), str(pole(r, "Round") or ""))
        wynik.append({
            "tura": tura, "data": data_str, "rok": int(data_str[:4]), "turniej": turniej, "poziom": poziom, "ranga": ranga,
            "nawierzchnia": nawierzchnia, "runda": runda,
            "zwyciezca": dopasuj(str(zw)), "zwyciezca_kraj": "", "przegrany": dopasuj(str(prz)), "przegrany_kraj": "",
            "wynik": wynik_str, "do_ilu_setow": _int(pole(r, "Best of")), "minuty": None,
            "ranking_zw": _int(pole(r, "WRank")), "ranking_prz": _int(pole(r, "LRank")),
            "asy_zw": None, "asy_prz": None, "podwojne_zw": None, "podwojne_prz": None,
            "zrodlo": "tennis-data.co.uk", "kolejnosc": nr,
            **{f"{cel}_{s}": None for cel in STATYSTYKI_SACKMANN.values() for s in ("zw", "prz")},
        })
    ks.close()
    return wynik


# ============================================================================= baza SQLite
def zbuduj_baze(od: int, do: int, tury: list[str]) -> Path:
    """Buduje dane/mecze.sqlite. Mecze wstawiamy plik po pliku (a nie wszystkie naraz z pamięci),
    dzięki czemu budowa zajmuje ok. 150 MB RAM zamiast ~1 GB – mieści się na darmowym hostingu."""
    cel = config.PLIK_BAZY_MECZOW
    cel.parent.mkdir(parents=True, exist_ok=True)
    tymczasowy = cel.with_suffix(".tmp")
    tymczasowy.unlink(missing_ok=True)
    db = sqlite3.connect(tymczasowy)
    db.execute(f"CREATE TABLE mecze (id INTEGER PRIMARY KEY, {', '.join(KOLUMNY)})")
    wstaw = f"INSERT INTO mecze ({', '.join(KOLUMNY)}) VALUES ({', '.join('?' * len(KOLUMNY))})"

    def dopisz(wiersze: list[dict]) -> None:
        for w in wiersze:
            w["turniej_norm"] = norm(w["turniej"])
            popraw_dane(w)
        db.executemany(wstaw, [[w[k] for k in KOLUMNY] for w in wiersze])

    # ostatnia data meczu u Sackmanna (osobno ATP i WTA) – tennis-data dokłada tylko mecze PÓŹNIEJSZE (bez duplikatów);
    # kraje i aktywność zawodników z danych Sackmanna – potrzebne do dopasowania nazwisk z tennis-data
    ostatnia_data: dict[str, str] = {}
    info: dict[str, tuple[int, int]] = {}
    kraje: dict[str, str] = {}
    sackmann = 0
    for plik in sorted(KATALOG_SACKMANN.glob("*_matches_*.csv")):
        tura = plik.name.split("_")[0]
        rok = _int(plik.stem.split("_")[-1])
        if not (tura in tury and rok is not None and od <= rok <= do):
            continue
        wiersze = wiersze_sackmann(plik)
        for w in wiersze:
            if w["data"] > ostatnia_data.get(w["tura"], ""):
                ostatnia_data[w["tura"]] = w["data"]
            for k, kraj_k in (("zwyciezca", "zwyciezca_kraj"), ("przegrany", "przegrany_kraj")):
                rok_ost, n = info.get(w[k], (0, 0))
                info[w[k]] = (max(rok_ost, w["rok"]), n + 1)
                if w[kraj_k]:
                    kraje[w[k]] = w[kraj_k]
        dopisz(wiersze)
        sackmann += len(wiersze)
    print(f"Sackmann: {sackmann:,} meczów".replace(",", " "))
    for t, d in sorted(ostatnia_data.items()):
        print(f"  {t}: dane Sackmanna do {d}")

    dopasuj = DopasowanieNazwisk(info)
    td = 0
    for plik in sorted(KATALOG_TD.glob("*.xlsx")):
        tura = plik.name.split("_")[0]
        rok = _int(plik.stem.split("_")[-1])
        if tura in tury and rok is not None and od <= rok <= do:
            try:
                nowe = wiersze_tennis_data(plik, dopasuj)
            except Exception as e:  # noqa: BLE001 – uszkodzony/nieoczekiwany plik nie może zatrzymać budowy bazy
                print(f"  Pomijam {plik.name}: {e}")
                continue
            nowe = [w for w in nowe if w["data"] > ostatnia_data.get(w["tura"], "")]
            for w in nowe:
                w["zwyciezca_kraj"] = kraje.get(w["zwyciezca"], "")
                w["przegrany_kraj"] = kraje.get(w["przegrany"], "")
            dopisz(nowe)
            td += len(nowe)
    print(f"tennis-data.co.uk: {td:,} meczów".replace(",", " "))
    if not sackmann + td:
        db.close()
        tymczasowy.unlink(missing_ok=True)
        raise SystemExit("Brak danych do zbudowania bazy – sprawdź, czy pliki zostały pobrane.")

    for kol in ("zwyciezca", "przegrany", "rok", "turniej_norm", "tura", "runda"):
        db.execute(f"CREATE INDEX idx_{kol} ON mecze({kol})")
    db.execute("""
        CREATE TABLE zawodnicy AS
        SELECT nazwa, tura, MAX(kraj) AS kraj, COUNT(*) AS mecze, MIN(rok) AS pierwszy_rok, MAX(rok) AS ostatni_rok FROM (
            SELECT zwyciezca AS nazwa, tura, NULLIF(zwyciezca_kraj, '') AS kraj, rok FROM mecze
            UNION ALL
            SELECT przegrany, tura, NULLIF(przegrany_kraj, ''), rok FROM mecze
        ) GROUP BY nazwa, tura""")
    db.execute("CREATE TABLE info (klucz TEXT PRIMARY KEY, wartosc TEXT)")
    db.executemany("INSERT INTO info VALUES (?, ?)", [
        ("utworzono", datetime.now().isoformat(timespec="seconds")),
        ("zrodla", "Jeff Sackmann / Tennis Abstract (CC BY-NC-SA 4.0), kopia Aneeshers/tennis-sackmann-archive; tennis-data.co.uk"),
    ])
    db.commit()
    db.close()
    tymczasowy.replace(cel)
    return cel


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--od", type=int, default=1968)
    p.add_argument("--do", type=int, default=date.today().year)
    p.add_argument("--tury", nargs="+", default=["atp", "wta"], choices=["atp", "wta"])
    p.add_argument("--challengery", action="store_true", help="dodaj challengery i kwalifikacje ATP")
    p.add_argument("--bez-pobierania", action="store_true", help="nie pobieraj, użyj plików z dysku")
    p.add_argument("--bez-biezacych", action="store_true", help="nie próbuj uzupełniać danych z tennis-data.co.uk")
    p.add_argument("--odswiez", action="store_true", help="pobierz pliki ponownie, nawet jeśli już są")
    a = p.parse_args()

    if not a.bez_pobierania:
        print(f"Pobieram dane Sackmanna z archiwalnej kopii ({', '.join(t.upper() for t in a.tury)}, {a.od}–{a.do})...")
        pobierz_sackmann(a.tury, a.od, a.do, a.challengery, a.odswiez)
        if not a.bez_biezacych:
            print("Próbuję uzupełnić najnowsze mecze z tennis-data.co.uk...")
            pobierz_tennis_data(a.tury, a.od, a.do, a.odswiez)
    print("Buduję bazę SQLite...")
    sciezka = zbuduj_baze(a.od, a.do, a.tury)
    db = sqlite3.connect(sciezka)
    n, od, do_ = db.execute("SELECT COUNT(*), MIN(rok), MAX(rok) FROM mecze").fetchone()
    z = db.execute("SELECT COUNT(*) FROM zawodnicy").fetchone()[0]
    print(f"\nGotowe: {sciezka}\n  meczów: {n:,}, zawodników: {z:,}, lata {od}–{do_}".replace(",", " "))
    print("Uruchom ponownie aplikację – czat i zakładka „Historia meczów” będą korzystać z bazy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
