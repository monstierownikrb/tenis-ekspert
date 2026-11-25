"""Czat w terminalu z Tenisowym Ekspertem.

Polecenia w trakcie rozmowy:
    /naucz <fakt>   – dodaj nowy fakt do bazy wiedzy (bot "uczy się")
    /zrodla         – pokaż fragmenty bazy użyte w ostatniej odpowiedzi
    /rag            – włącz/wyłącz korzystanie z bazy wiedzy (do porównań)
    /nowa           – zacznij nową rozmowę (wyczyść historię)
    /wyjdz          – zakończ
"""
from __future__ import annotations

import sys

import config
from silnik import BladOllamy, utworz_bota


def main() -> int:
    try:
        bot = utworz_bota(config)
    except (FileNotFoundError, ValueError) as e:
        print(e)
        return 1
    problemy = bot.klient.sprawdz()
    if problemy:
        print("Uwaga:\n  - " + "\n  - ".join(problemy))
        return 1

    print("🎾 Tenisowy Ekspert – zadaj pytanie o tenis (polecenia: /naucz, /zrodla, /rag, /nowa, /wyjdz)")
    print(f"   Model: {config.MODEL_LLM} | embeddingi: {config.MODEL_EMBED} | fragmentów w bazie: {len(bot.indeks.fragmenty)}")
    print(f"   Baza meczów: {bot.baza_meczow.opis_zakresu() if bot.baza_meczow else 'brak (python -m narzedzia.pobierz_mecze)'}\n")
    rozmowa: list[dict] = []
    ostatnie_trafienia = []
    ostatnie_mecze = None
    uzyj_rag = True

    while True:
        try:
            pytanie = input("Ty: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not pytanie:
            continue
        if pytanie in ("/wyjdz", "/exit", "/quit"):
            break
        if pytanie == "/nowa":
            rozmowa.clear()
            print("(nowa rozmowa)\n")
            continue
        if pytanie == "/rag":
            uzyj_rag = not uzyj_rag
            print(f"(baza wiedzy {'WŁĄCZONA' if uzyj_rag else 'WYŁĄCZONA – model odpowiada tylko z własnej pamięci'})\n")
            continue
        if pytanie == "/zrodla":
            if ostatnie_mecze is not None:
                print(f"[M] baza meczów ({ostatnie_mecze.rodzaj}):\n{ostatnie_mecze.tekst}\n")
            if not ostatnie_trafienia:
                print("(brak źródeł)\n")
            for nr, t in enumerate(ostatnie_trafienia, 1):
                print(f"[{nr}] {t.fragment.zrodlo} | {t.fragment.tytul} (podob. {t.podobienstwo:.2f}, BM25 {t.bm25:.1f})")
            print()
            continue
        if pytanie.startswith("/naucz"):
            fakt = pytanie[len("/naucz"):].strip()
            try:
                bot.naucz(fakt)
                print("Zapamiętałem! Ten fakt jest już w bazie wiedzy.\n")
            except (ValueError, BladOllamy) as e:
                print(f"Nie udało się: {e}\n")
            continue

        try:
            odp = bot.zapytaj(pytanie, rozmowa, uzyj_rag=uzyj_rag)
            print("Ekspert: ", end="", flush=True)
            for kawalek in odp.strumien:
                print(kawalek, end="", flush=True)
            print("\n")
        except BladOllamy as e:
            print(f"\n[Błąd] {e}\n")
            continue
        ostatnie_trafienia = odp.trafienia
        ostatnie_mecze = odp.mecze
        rozmowa += [{"role": "user", "content": pytanie}, {"role": "assistant", "content": odp.tekst}]
    return 0


if __name__ == "__main__":
    sys.exit(main())
