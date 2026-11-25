"""Generuje TESTOWE pliki meczów w formatach Sackmanna (CSV) i tennis-data.co.uk (XLSX).

Bazują na prawdziwych finałach Wielkiego Szlema z dane_zrodlowe/ (oraz kilku dodatkowych meczach),
ale to tylko mała próbka do sprawdzenia kodu – prawdziwe dane pobiera narzedzia/pobierz_mecze.py.
"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

KATALOG = Path(__file__).resolve().parent.parent
KOLUMNY_SACKMANN = [
    "tourney_id", "tourney_name", "surface", "draw_size", "tourney_level", "tourney_date", "match_num",
    "winner_id", "winner_seed", "winner_entry", "winner_name", "winner_hand", "winner_ht", "winner_ioc", "winner_age",
    "loser_id", "loser_seed", "loser_entry", "loser_name", "loser_hand", "loser_ht", "loser_ioc", "loser_age",
    "score", "best_of", "round", "minutes", "w_ace", "w_df", "w_svpt", "w_1stIn", "w_1stWon", "w_2ndWon", "w_SvGms",
    "w_bpSaved", "w_bpFaced", "l_ace", "l_df", "l_svpt", "l_1stIn", "l_1stWon", "l_2ndWon", "l_SvGms", "l_bpSaved",
    "l_bpFaced", "winner_rank", "winner_rank_points", "loser_rank", "loser_rank_points",
]
MIESIAC = {"Australian Open": "0115", "Roland Garros": "0526", "Wimbledon": "0624", "US Open": "0826"}


def nawierzchnia(turniej: str, rok: int) -> str:
    if turniej == "Roland Garros":
        return "Clay"
    if turniej == "Wimbledon":
        return "Grass"
    if turniej == "Australian Open":
        return "Hard" if rok >= 1988 else "Grass"
    return "Grass" if rok <= 1974 else ("Clay" if rok <= 1977 else "Hard")


# kilka dodatkowych (prawdziwych) meczów spoza finałów – do testów bilansów i filtrów
DODATKOWE = [
    ("ATP", "2019", "Wimbledon", "G", "SF", "Roger Federer", "SUI", "Rafael Nadal", "ESP", "7-6(3) 1-6 6-3 6-4"),
    ("ATP", "2021", "Wimbledon", "G", "QF", "Hubert Hurkacz", "POL", "Roger Federer", "SUI", "6-3 7-6(4) 6-0"),
    ("ATP", "2021", "Wimbledon", "G", "R16", "Hubert Hurkacz", "POL", "Daniil Medvedev", "RUS", "2-6 7-6(2) 3-6 6-3 6-3"),
    ("ATP", "2021", "Miami Masters", "M", "F", "Hubert Hurkacz", "POL", "Jannik Sinner", "ITA", "7-6(4) 6-4"),
    ("ATP", "2023", "Shanghai Masters", "M", "F", "Hubert Hurkacz", "POL", "Andrey Rublev", "RUS", "6-3 3-6 7-6(8)"),
    ("WTA", "2012", "Wimbledon", "G", "SF", "Agnieszka Radwanska", "POL", "Angelique Kerber", "GER", "6-3 6-4"),
    ("WTA", "2015", "Tour Finals", "F", "F", "Agnieszka Radwanska", "POL", "Petra Kvitova", "CZE", "6-2 4-6 6-3"),
]


def sackmann(cel: Path) -> None:
    with open(KATALOG / "dane_zrodlowe" / "finaly_wielkiego_szlema.csv", encoding="utf-8") as f:
        finaly = list(csv.DictReader(f))
    pliki: dict[tuple[str, int], list[dict]] = {}
    for nr, w in enumerate(finaly):
        rok = int(w["rok"])
        if rok > 2024:
            continue
        tura = "WTA" if w["plec"] == "kobiety" else "ATP"
        data = f"{rok}{'1219' if w['edycja'] == 'grudzień' else MIESIAC[w['turniej']]}"
        pliki.setdefault((tura, rok), []).append({
            "tourney_id": f"{rok}-{nr}", "tourney_name": w["turniej"], "surface": nawierzchnia(w["turniej"], rok),
            "draw_size": "128", "tourney_level": "G", "tourney_date": data, "match_num": "127",
            "winner_name": w["zwyciezca"], "winner_ioc": w["kraj_zwyciezcy"], "loser_name": w["finalista"],
            "loser_ioc": w["kraj_finalisty"], "score": w["wynik"].replace("–", "-").replace(", ", " "),
            "best_of": "3" if tura == "WTA" else "5", "round": "F", "w_ace": "10", "l_ace": "5",
        })
    for nr, (tura, rok, turniej, poziom, runda, zw, kzw, prz, kprz, wynik) in enumerate(DODATKOWE):
        pliki.setdefault((tura, int(rok)), []).append({
            "tourney_id": f"{rok}-x{nr}", "tourney_name": turniej,
            "surface": "Grass" if turniej == "Wimbledon" else "Hard", "draw_size": "128", "tourney_level": poziom,
            "tourney_date": f"{rok}{MIESIAC.get(turniej, '0320')}", "match_num": str(100 + nr),
            "winner_name": zw, "winner_ioc": kzw, "loser_name": prz, "loser_ioc": kprz, "score": wynik,
            "best_of": "3" if tura == "WTA" else "5", "round": runda,
        })
    for (tura, rok), wiersze in pliki.items():
        t = tura.lower()
        sciezka = cel / t / f"{t}_matches_{rok}.csv"
        sciezka.parent.mkdir(parents=True, exist_ok=True)
        with open(sciezka, "w", newline="", encoding="utf-8") as f:
            pis = csv.DictWriter(f, fieldnames=KOLUMNY_SACKMANN)
            pis.writeheader()
            for w in wiersze:
                pis.writerow({k: w.get(k, "") for k in KOLUMNY_SACKMANN})


def tennis_data(cel: Path) -> None:
    from openpyxl import Workbook

    naglowek = ["ATP", "Location", "Tournament", "Date", "Series", "Court", "Surface", "Round", "Best of", "Winner",
                "Loser", "WRank", "LRank", "W1", "L1", "W2", "L2", "W3", "L3", "W4", "L4", "W5", "L5", "Wsets", "Lsets",
                "Comment"]
    mecze = {
        ("atp", 2025): [
            ("Melbourne", "Australian Open", "2025-01-26", "Grand Slam", "Hard", "The Final", 5, "Sinner J.", "Zverev A.", 1, 2, [(6, 3), (7, 6), (6, 3)], "Completed"),
            ("Paris", "French Open", "2025-06-08", "Grand Slam", "Clay", "The Final", 5, "Alcaraz C.", "Sinner J.", 2, 1, [(4, 6), (6, 7), (6, 4), (7, 6), (7, 6)], "Completed"),
            ("Geneva", "Gonet Geneva Open", "2025-05-24", "ATP250", "Clay", "The Final", 3, "Djokovic N.", "Hurkacz H.", 6, 31, [(5, 7), (7, 6), (7, 6)], "Completed"),
            ("Rio", "Rio Open", "2025-02-20", "ATP500", "Clay", "2nd Round", 3, "Nowak T.", "Hurkacz H.", 60, 20, [(6, 4), (3, 0)], "Retired"),
        ],
        ("atp", 2026): [
            ("Melbourne", "Australian Open", "2026-02-01", "Grand Slam", "Hard", "The Final", 5, "Alcaraz C.", "Djokovic N.", 1, 4, [(2, 6), (6, 2), (6, 3), (7, 5)], "Completed"),
            ("Paris", "French Open", "2026-06-07", "Grand Slam", "Clay", "The Final", 5, "Zverev A.", "Cobolli F.", 3, 15, [(6, 1), (4, 6), (6, 4), (6, 7), (6, 1)], "Completed"),
        ],
        ("wta", 2026): [
            ("Paris", "French Open", "2026-06-06", "Grand Slam", "Clay", "The Final", 3, "Andreeva M.", "Chwalinska M.", 8, 80, [(6, 3), (6, 2)], "Completed"),
            ("Melbourne", "Australian Open", "2026-01-31", "Grand Slam", "Hard", "The Final", 3, "Rybakina E.", "Sabalenka A.", 3, 1, [(6, 4), (4, 6), (6, 4)], "Completed"),
            ("Melbourne", "Australian Open", "2026-01-27", "Grand Slam", "Hard", "Quarterfinals", 3, "Rybakina E.", "Swiatek I.", 3, 2, [(7, 5), (6, 1)], "Completed"),
        ],
    }
    for (tura, rok), wiersze in mecze.items():
        wb = Workbook()
        ark = wb.active
        ark.append(naglowek if tura == "atp" else [("WTA" if h == "ATP" else "Tier" if h == "Series" else h) for h in naglowek])
        for nr, (miasto, turniej, data, seria, naw, runda, bo, zw, prz, wr, lr, sety, kom) in enumerate(wiersze):
            wiersz = [nr + 1, miasto, turniej, datetime.strptime(data, "%Y-%m-%d"), seria, "Outdoor", naw, runda, bo, zw, prz, wr, lr]
            for i in range(5):
                wiersz += list(sety[i]) if i < len(sety) else [None, None]
            wiersz += [sum(a > b for a, b in sety), sum(a < b for a, b in sety), kom]
            ark.append(wiersz)
        katalog = cel / (f"{rok}w" if tura == "wta" else f"{rok}")
        katalog.mkdir(parents=True, exist_ok=True)
        wb.save(katalog / f"{rok}.xlsx")


def utworz(cel: Path) -> Path:
    sackmann(cel)
    tennis_data(cel)
    return cel


if __name__ == "__main__":
    print(utworz(Path(__file__).resolve().parent / "_serwer_danych"))
