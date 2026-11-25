"""Ewaluacja chatbota na zestawie pytań testowych (testy/pytania_testowe.json).

Mierzymy:
  1. Trafność wyszukiwania (recall@k) – czy wśród k znalezionych fragmentów (i danych z bazy meczów) jest odpowiedź.
  2. Trafność odpowiedzi BEZ bazy wiedzy (sam model)  – pokazuje, ile model "pamięta" i jak często zmyśla.
  3. Trafność odpowiedzi Z bazą wiedzy (RAG)          – pokazuje zysk z RAG.
Odpowiedź uznajemy za poprawną, jeśli zawiera oczekiwane słowa kluczowe (bez polskich znaków, bez wielkości liter).

Użycie:
    python ewaluacja.py                    # wszystko (kilka minut – zależy od modelu)
    python ewaluacja.py --tylko-wyszukiwanie
    python ewaluacja.py --limit 10         # szybki test na 10 pytaniach
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime

import config
from silnik import BladOllamy, utworz_bota
from silnik.tekst import bez_ogonkow

PLIK_PYTAN = config.KATALOG_PROJEKTU / "testy" / "pytania_testowe.json"
KATALOG_WYNIKOW = config.KATALOG_PROJEKTU / "wyniki"


def znormalizuj(tekst: str) -> str:
    return bez_ogonkow(tekst.lower()).replace("–", "-").replace(" ", " ")


def zawiera_odpowiedz(tekst: str, oczekiwane: list[list[str]]) -> bool:
    """Każda grupa musi być spełniona; w grupie wystarczy jeden z wariantów."""
    t = znormalizuj(tekst)
    return all(any(znormalizuj(w) in t for w in grupa) for grupa in oczekiwane)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tylko-wyszukiwanie", action="store_true", help="mierz tylko trafność wyszukiwania (bez LLM)")
    parser.add_argument("--limit", type=int, default=0, help="użyj tylko N pierwszych pytań")
    args = parser.parse_args()

    pytania = json.loads(PLIK_PYTAN.read_text(encoding="utf-8"))
    if args.limit:
        pytania = pytania[: args.limit]
    try:
        bot = utworz_bota(config)
    except (FileNotFoundError, ValueError) as e:
        print(e)
        return 1

    if bot.baza_meczow is None:
        pominiete = [p for p in pytania if p.get("wymaga_bazy_meczow")]
        if pominiete:
            print(f"(Pomijam {len(pominiete)} pytań wymagających bazy meczów – utwórz ją: python -m narzedzia.pobierz_mecze)\n")
        pytania = [p for p in pytania if not p.get("wymaga_bazy_meczow")]

    wiersze = []
    for nr, p in enumerate(pytania, 1):
        trafienia = bot.wyszukaj(p["pytanie"])
        mecze = bot.kontekst_meczow(p["pytanie"], [])
        kontekst = "\n".join(t.fragment.tekst for t in trafienia) + ("\n" + mecze.tekst if mecze else "")
        wiersz = {"nr": nr, "pytanie": p["pytanie"], "kategoria": p.get("kategoria", ""),
                  "wyszukiwanie_ok": zawiera_odpowiedz(kontekst, p["oczekiwane"])}
        if not args.tylko_wyszukiwanie:
            try:
                t0 = time.time()
                bez = bot.zapytaj_tekst(p["pytanie"], uzyj_rag=False).tekst
                t1 = time.time()
                z = bot.zapytaj_tekst(p["pytanie"], uzyj_rag=True).tekst
                t2 = time.time()
            except BladOllamy as e:
                print(f"\n{e}")
                return 1
            wiersz.update({"bez_rag_ok": zawiera_odpowiedz(bez, p["oczekiwane"]), "rag_ok": zawiera_odpowiedz(z, p["oczekiwane"]),
                           "odp_bez_rag": bez, "odp_rag": z, "czas_bez_rag": t1 - t0, "czas_rag": t2 - t1})
        wiersze.append(wiersz)
        znaczki = "W:" + ("✔" if wiersz["wyszukiwanie_ok"] else "✘")
        if not args.tylko_wyszukiwanie:
            znaczki += "  bezRAG:" + ("✔" if wiersz["bez_rag_ok"] else "✘") + "  RAG:" + ("✔" if wiersz["rag_ok"] else "✘")
        print(f"{nr:>2}. {znaczki}  {p['pytanie']}")

    n = len(wiersze)
    def proc(klucz: str) -> str:
        return f"{sum(w[klucz] for w in wiersze)}/{n} ({100 * sum(w[klucz] for w in wiersze) / n:.0f}%)"

    print("\n=== PODSUMOWANIE ===")
    print(f"Trafność wyszukiwania (recall@{bot.top_k}): {proc('wyszukiwanie_ok')}")
    if not args.tylko_wyszukiwanie:
        print(f"Poprawne odpowiedzi BEZ bazy wiedzy:   {proc('bez_rag_ok')}")
        print(f"Poprawne odpowiedzi Z bazą wiedzy (RAG): {proc('rag_ok')}")

    # raport Markdown – gotowy do wklejenia do sprawozdania
    KATALOG_WYNIKOW.mkdir(exist_ok=True)
    plik = KATALOG_WYNIKOW / f"ewaluacja_{datetime.now():%Y%m%d_%H%M%S}.md"
    linie = [f"# Ewaluacja chatbota – {datetime.now():%Y-%m-%d %H:%M}", "",
             f"- Model LLM: `{config.MODEL_LLM}`, embeddingi: `{config.MODEL_EMBED}`, top-k: {bot.top_k}",
             f"- Baza meczów: {bot.baza_meczow.opis_zakresu() if bot.baza_meczow else 'brak'}",
             f"- Liczba pytań: {n}", f"- Trafność wyszukiwania: **{proc('wyszukiwanie_ok')}**"]
    if not args.tylko_wyszukiwanie:
        linie += [f"- Poprawne odpowiedzi bez RAG: **{proc('bez_rag_ok')}**",
                  f"- Poprawne odpowiedzi z RAG: **{proc('rag_ok')}**", "",
                  "| # | Pytanie | Wyszukiwanie | Bez RAG | RAG |", "|---|---|---|---|---|"]
        for w in wiersze:
            linie.append(f"| {w['nr']} | {w['pytanie']} | {'✔' if w['wyszukiwanie_ok'] else '✘'} | "
                         f"{'✔' if w['bez_rag_ok'] else '✘'} | {'✔' if w['rag_ok'] else '✘'} |")
        linie += ["", "## Odpowiedzi", ""]
        for w in wiersze:
            linie += [f"### {w['nr']}. {w['pytanie']}", f"**Bez RAG:** {w['odp_bez_rag']}", "", f"**Z RAG:** {w['odp_rag']}", ""]
    else:
        linie += ["", "| # | Pytanie | Wyszukiwanie |", "|---|---|---|"]
        linie += [f"| {w['nr']} | {w['pytanie']} | {'✔' if w['wyszukiwanie_ok'] else '✘'} |" for w in wiersze]
    plik.write_text("\n".join(linie), encoding="utf-8")
    print(f"\nRaport zapisano: {plik}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
