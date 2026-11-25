"""Rozszerza bazę wiedzy o artykuły z polskiej Wikipedii (opcjonalnie – wymaga internetu).

Pobiera czysty tekst artykułów przez oficjalne API Wikipedii i zapisuje je jako pliki Markdown
w baza_wiedzy/wikipedia/. Potem przebuduj indeks:  python zbuduj_baze.py

Użycie:
    python -m narzedzia.pobierz_wikipedia                        # domyślna lista haseł o tenisie
    python -m narzedzia.pobierz_wikipedia "Hubert Hurkacz" "Wimbledon"

Treści z Wikipedii są na licencji CC BY-SA – w sprawozdaniu podaj źródło.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

KATALOG = Path(__file__).resolve().parent.parent / "baza_wiedzy" / "wikipedia"
API = "https://pl.wikipedia.org/w/api.php"
NAGLOWKI = {"User-Agent": "TenisowyEkspert/1.0 (projekt studencki; chatbot RAG)"}

DOMYSLNE_HASLA = [
    "Tenis", "Wielki Szlem (tenis)", "Australian Open", "French Open", "Wimbledon (turniej tenisowy)", "US Open (tenis)",
    "Puchar Davisa", "Billie Jean King Cup", "Association of Tennis Professionals", "Women’s Tennis Association",
    "Iga Świątek", "Hubert Hurkacz", "Agnieszka Radwańska", "Wojciech Fibak", "Jadwiga Jędrzejowska",
    "Roger Federer", "Rafael Nadal", "Novak Đoković", "Serena Williams", "Carlos Alcaraz", "Jannik Sinner",
]


def pobierz(tytul: str) -> tuple[str, str] | None:
    parametry = {
        "action": "query", "prop": "extracts", "explaintext": 1, "redirects": 1,
        "format": "json", "formatversion": 2, "titles": tytul,
    }
    url = API + "?" + urllib.parse.urlencode(parametry)
    with urllib.request.urlopen(urllib.request.Request(url, headers=NAGLOWKI), timeout=30) as odp:
        dane = json.loads(odp.read().decode("utf-8"))
    return przetworz_odpowiedz(dane)


def przetworz_odpowiedz(dane: dict) -> tuple[str, str] | None:
    strony = dane.get("query", {}).get("pages", [])
    if not strony or strony[0].get("missing") or not strony[0].get("extract"):
        return None
    return strony[0]["title"], strony[0]["extract"]


def na_markdown(tytul: str, tekst: str) -> str:
    """Nagłówki Wikipedii (== Sekcja ==) zamieniamy na '## Sekcja', żeby dzielenie na fragmenty działało."""
    pomijane = {"Przypisy", "Bibliografia", "Linki zewnętrzne", "Zobacz też", "Uwagi"}
    linie_wyj = [f"# {tytul} (Wikipedia)", ""]
    pomijaj = False
    for linia in tekst.splitlines():
        m = re.match(r"^(=+)\s*(.+?)\s*\1\s*$", linia)
        if m:
            nazwa = m.group(2)
            pomijaj = nazwa in pomijane
            if not pomijaj:
                linie_wyj.append(f"## {tytul} – {nazwa}")
            continue
        if not pomijaj:
            linie_wyj.append(linia)
    linie_wyj += ["", f"Źródło: Wikipedia, hasło „{tytul}” (licencja CC BY-SA 4.0)."]
    return "\n".join(linie_wyj)


def main(hasla: list[str]) -> int:
    KATALOG.mkdir(parents=True, exist_ok=True)
    for haslo in hasla:
        try:
            wynik = pobierz(haslo)
        except Exception as e:  # noqa: BLE001
            print(f"✘ {haslo}: błąd pobierania ({e})")
            continue
        if not wynik:
            print(f"✘ {haslo}: nie znaleziono hasła")
            continue
        tytul, tekst = wynik
        nazwa_pliku = re.sub(r"[^\w\-]+", "_", tytul).strip("_") + ".md"
        (KATALOG / nazwa_pliku).write_text(na_markdown(tytul, tekst), encoding="utf-8")
        print(f"✔ {tytul} ({len(tekst)} znaków) -> {nazwa_pliku}")
        time.sleep(0.5)  # nie obciążamy serwerów Wikipedii
    print("\nGotowe. Teraz przebuduj indeks: python zbuduj_baze.py")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or DOMYSLNE_HASLA))
