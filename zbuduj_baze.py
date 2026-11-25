"""Buduje indeks wiedzy: czyta pliki z baza_wiedzy/, dzieli na fragmenty, liczy embeddingi i zapisuje do indeks/.

Użycie:
    python zbuduj_baze.py            # przebudowa – embeddingi liczone tylko dla nowych/zmienionych fragmentów
    python zbuduj_baze.py --od-nowa  # wszystkie embeddingi od nowa
    python zbuduj_baze.py --podglad  # tylko pokaż, jakie fragmenty powstaną (bez Ollamy)
"""
from __future__ import annotations

import argparse
import sys
import time

import config
from silnik import BladOllamy, IndeksHybrydowy, utworz_klienta, wczytaj_fragmenty_bazy


def pasek(zrobione: int, wszystkie: int) -> None:
    szer = 30
    pelne = int(szer * zrobione / max(wszystkie, 1))
    print(f"\r  Embeddingi: [{'#' * pelne}{'.' * (szer - pelne)}] {zrobione}/{wszystkie}", end="", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--podglad", action="store_true", help="pokaż statystyki fragmentów bez liczenia embeddingów")
    parser.add_argument("--od-nowa", action="store_true", help="nie korzystaj z wektorów z poprzedniego indeksu")
    args = parser.parse_args()

    if not (config.KATALOG_BAZY / "wielki_szlem").exists():
        print("Brak wygenerowanych plików o finałach Wielkiego Szlema – generuję...")
        from narzedzia.generuj_szlemy import main as generuj
        generuj()

    fragmenty = wczytaj_fragmenty_bazy(config.KATALOG_BAZY, config.MAX_ZNAKOW_FRAGMENTU, config.ZAKLADKA_ZNAKOW)
    pliki = sorted({f.zrodlo for f in fragmenty})
    print(f"Baza wiedzy: {len(pliki)} plików -> {len(fragmenty)} fragmentów")

    if args.podglad:
        dl = [len(f.tekst) for f in fragmenty]
        print(f"  długość fragmentu: min {min(dl)}, średnio {sum(dl) // len(dl)}, max {max(dl)} znaków")
        for f in fragmenty[:3]:
            print("-" * 60 + f"\n{f.id}\n{f.tekst[:300]}")
        return 0

    klient = utworz_klienta(config)
    problemy = [p for p in klient.sprawdz() if "embeddingów" in p or "połączyć" in p]
    if problemy:
        print("\nNie mogę zbudować indeksu:\n  - " + "\n  - ".join(problemy))
        return 1

    pamiec = {} if args.od_nowa else IndeksHybrydowy.pamiec_z_katalogu(config.KATALOG_INDEKSU, config.MODEL_EMBED)
    nowe = sum(1 for f in fragmenty if f.tekst not in pamiec)
    if pamiec:
        print(f"Z poprzedniego indeksu biorę {len(fragmenty) - nowe} fragmentów, liczę od nowa: {nowe}.")
    if nowe:
        print(f"Liczę embeddingi modelem '{config.MODEL_EMBED}' (pierwsze uruchomienie może potrwać)...")
    start = time.time()
    indeks = IndeksHybrydowy(klient.embed if config.MODEL_EMBED else None, config.MODEL_EMBED)
    try:
        indeks.zbuduj(fragmenty, postep=pasek, pamiec=pamiec)
    except BladOllamy as e:
        print(f"\n{e}")
        print("Uruchom polecenie jeszcze raz.")
        return 1
    indeks.zapisz(config.KATALOG_INDEKSU)
    print(f"\nGotowe w {time.time() - start:.0f} s. Indeks zapisany w: {config.KATALOG_INDEKSU}")
    print(f"Wymiar wektora: {indeks.wektory.shape[1]}, liczba fragmentów: {len(indeks.fragmenty)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
