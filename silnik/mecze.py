"""Baza meczów (SQLite) – pełna historia singla ATP i WTA – oraz zamiana pytania na zapytania SQL.

Dlaczego osobna baza, a nie RAG?
Pytania typu „jaki jest bilans Nadal–Federer?” albo „ile meczów wygrał Hurkacz w 2023?” wymagają
LICZENIA po tysiącach meczów. Model językowy liczy źle, a wyszukiwarka fragmentów nie znajdzie
„sumy”. Dlatego liczy SQL (dokładnie), a model dostaje gotowe wyniki w kontekście i tylko je opisuje.

Jak pytanie zamienia się na zapytanie:
1. rozpoznajemy zawodników (także w odmianie: „Nadala”, „Djokovicia”, „Sabalenki”),
2. rozpoznajemy filtry: lata, turniej, rundę, nawierzchnię, tour (ATP/WTA),
3. wybieramy typ zestawienia: bilans dwóch zawodników / kariera jednego / wyniki turnieju.
"""
from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .tekst import bez_ogonkow, wyglada_na_uzupelniajace


def norm(tekst: str) -> str:
    """Normalizacja nazw: małe litery, bez ogonków, myślniki i kropki -> spacje."""
    t = bez_ogonkow(str(tekst).lower()).replace("-", " ").replace(".", " ").replace("'", " ")
    return re.sub(r"\s+", " ", t).strip()


# ----------------------------------------------------------------------------- słowniki
# Rozgrywki drużynowe: wygrany „finał” to nie tytuł zawodnika (np. United Cup 2026 Hurkacza).
_DRUZYNOWE = re.compile(r"united cup|atp cup|laver cup|nations cup|world team|hopman|davis cup|bjk cup|fed cup|"
                        r"wightman|bonne bell", re.I)


# Czasowniki w 3. osobie bez podmiotu („Ile tytułów zdobył?”) – podmiotem jest zawodnik z poprzedniego pytania.
_CZASOWNIKI_BEZ_PODMIOTU = (r"\b(wygral|wygrala|zdobyl|zdobyla|przegral|przegrala|pokonal|pokonala|zagral|zagrala|"
                            r"gral|grala|zaserwowal|zaserwowala|doszedl|doszla|zakonczyl|zakonczyla|zadebiutowal|"
                            r"zadebiutowala|ma|mial|miala)\b")


def turniej_druzynowy(turniej: str | None, poziom: str | None) -> bool:
    return poziom == "D" or bool(_DRUZYNOWE.search(turniej or ""))


RANGI = {
    "G": "Wielki Szlem", "M": "Masters 1000", "A": "turniej ATP", "F": "turniej finałowy (ATP/WTA Finals)",
    "D": "Puchar Davisa / BJK Cup", "O": "igrzyska olimpijskie", "C": "Challenger", "S": "ITF",
    "PM": "WTA Premier Mandatory", "P": "WTA Premier", "I": "WTA International", "W": "WTA 1000",
    "T1": "WTA Tier I", "T2": "WTA Tier II", "T3": "WTA Tier III", "T4": "WTA Tier IV", "T5": "WTA Tier V",
    "E": "pokazowy / inny", "J": "juniorski",
}
NAWIERZCHNIE = {"Hard": "twarda", "Clay": "ziemna (mączka)", "Grass": "trawa", "Carpet": "dywan (hala)"}
RUNDY = {"F": "finał", "SF": "półfinał", "QF": "ćwierćfinał", "R16": "1/8 finału", "R32": "1/16 finału",
         "R64": "1/32 finału", "R128": "1. runda (128)", "RR": "faza grupowa", "BR": "mecz o brąz",
         "1R": "1. runda", "2R": "2. runda", "3R": "3. runda", "4R": "4. runda"}

# Turnieje: klucz -> (wzorce w nazwie turnieju w bazie, wzorce w pytaniu)
TURNIEJE = {
    "Australian Open": (["australian open", "australian chps", "australian championships"],
                        [r"australian open", r"\bao\b", r"melbourn", r"mistrzostw\w* australii", r"otwart\w* mistrzostw\w* australii"]),
    "Roland Garros": (["roland garros", "french open"],
                      [r"roland\s*garros", r"french open", r"\brg\b", r"mistrzostw\w* francji", r"paryz(?!\w* masters)"]),
    "Wimbledon": (["wimbledon"], [r"wimbledon"]),
    "US Open": (["us open", "u s open", "us championships", "u s national"],
                [r"us open", r"\buso\b", r"nowym jorku", r"nowy jork", r"flushing", r"mistrzostw\w* usa"]),
    "ATP/WTA Finals": (["tour finals", "masters cup", "atp finals", "wta finals", "wta championships", "tour championships", "masters"],
                       [r"atp finals", r"wta finals", r"masters cup", r"turniej\w* finalow", r"turyn", r"finals"]),
    "Indian Wells": (["indian wells", "bnp paribas open"], [r"indian wells"]),
    "Miami": (["miami"], [r"miami"]),
    "Monte Carlo": (["monte carlo"], [r"monte carlo"]),
    "Madryt": (["madrid"], [r"madryt", r"madrid"]),
    "Rzym": (["rome", "internazionali", "italian open"], [r"rzym", r"\brome\b", r"italian open"]),
    "Kanada": (["canada", "canadian", "toronto", "montreal", "national bank", "rogers"], [r"kanad", r"toronto", r"montreal"]),
    "Cincinnati": (["cincinnati", "western southern"], [r"cincinnati"]),
    "Szanghaj": (["shanghai"], [r"szanghaj", r"shanghai"]),
    "Paris Masters": (["paris masters", "paris", "bercy"], [r"paris masters", r"bercy", r"paryz\w* masters"]),
    "Igrzyska olimpijskie": (["olympics", "olympic"], [r"olimpi", r"igrzysk"]),
    "Puchar Davisa": (["davis cup"], [r"puchar\w* davisa", r"davis cup"]),
    "Billie Jean King Cup": (["fed cup", "bjk cup", "billie jean king cup"],
                             [r"billie jean king cup", r"\bbjk\b", r"fed cup", r"puchar\w* federacji"]),
}

# Polskie (fonetyczne) zapisy nazwisk -> zapis w bazie
ALIASY = {
    "dzokovic": "djokovic", "dzokowic": "djokovic", "djokowic": "djokovic", "miedwiediew": "medvedev",
    "zwieriew": "zverev", "zwierew": "zverev", "szarapow": "sharapova", "andriejew": "andreeva",
    "rublow": "rublev", "chaczanow": "khachanov", "kuzniecow": "kuznetsova", "switolin": "svitolina",
    "kostiuk": "kostyuk", "noskow": "noskova", "muchow": "muchova", "kwitow": "kvitova", "azarenk": "azarenka",
    "kafielnikow": "kafelnikov", "diemientjew": "dementieva", "zwonariow": "zvonareva",
    "cilicz": "cilic", "pliskow": "pliskova",
    "krejcikow": "krejcikova", "vondrousow": "vondrousova", "alexandrow": "alexandrova",
}

# Słowa z pytań, które nie mogą być nazwiskami (np. "Davis", "Open", "King" w innym znaczeniu)
NIE_NAZWISKA = {
    "open", "davis", "cup", "masters", "finals", "final", "finale", "finalu", "wimbledon", "wimbledonie", "roland",
    "garros", "australian", "turniej", "turnieju", "turniejach", "mecz", "meczu", "mecze", "meczow", "wygral",
    "wygrala", "przegral", "przegrala", "bilans", "kto", "ile", "razy", "roku", "latach", "tenis", "atp", "wta",
    "kariera", "karierze", "pokonal", "pokonala", "grali", "graly", "gral", "grala", "miami", "madrid",
    "rome", "paris", "shanghai", "monte", "carlo", "indian", "wells", "cincinnati", "us", "uso", "rg", "ao",
    "set", "sety", "seta", "tie", "break", "mistrz", "mistrzyni", "finalista", "polfinal", "cwiercfinal",
    "przeciwko", "kontra", "vs", "versus", "przeciw", "head", "to", "statystyki", "historia", "wszystkie",
    "najwiecej", "pierwszy", "ostatni", "ostatnie", "mecza", "zawodnik", "zawodniczka", "trawie", "maczce",
    "kim", "kogo", "komu", "czym", "czy", "jak", "jaki", "jaka", "jakie", "jaki", "ktory", "ktora", "ktore",
    "kiedy", "gdzie", "dlaczego", "przy", "nad", "pod", "dla", "przez", "jest", "byl", "byla", "bylo", "sie",
    "oraz", "albo", "tylko", "mial", "miala", "jego", "jej", "ich", "tym", "tego", "podaj", "powiedz", "opisz",
    "pokaz", "wszystkich", "lista", "liste", "sezon", "sezonie", "grand", "slam", "szlem", "szlema", "wielki",
    "wielkiego", "wielkim", "ranking", "rankingu", "lider", "liderem", "tytul", "tytulow", "tytuly", "rok",
    "lat", "lata", "mistrzem", "mistrzynia", "finale", "finalu", "finalow", "polfinale", "rundzie", "runda",
    "nawierzchni", "korcie", "kortach", "olimpijski", "igrzyska", "puchar", "pucharze", "the", "and", "for",
    "about", "who", "won", "win", "match", "matches", "between", "all", "time", "best", "more", "most",
}

_SLOWA_STATYSTYK = (r"\basy\b|\basow\b|\basami\b|\basa\b|\baces?\b|statystyk\w*|serwis\w*|podani\w*|podwojn\w*|"
                    r"break\s*point\w*|przelaman\w*|return\w*|odbior\w*|minut\w*|trwal\w*|czas\w* (meczu|gry)|"
                    r"procent\w*|skutecznos\w*|pierwsz\w* serw\w*|drugi\w* serw\w*")
_SLOWA_KOBIETY = r"\b(kobiet\w*|wta|zawodniczk\w*|tenisistk\w*)"
_SLOWA_MEZCZYZNI = r"\b(mezczyzn\w*|panow|atp|zawodnik\w*|tenisist(?!k)\w*)"


@dataclass
class Zawodnik:
    nazwa: str
    tura: str
    kraj: str
    mecze: int
    pierwszy_rok: int
    ostatni_rok: int
    norm_pelna: str = ""
    nazwisko: str = ""  # ostatni człon nazwiska (znormalizowany)
    imie: str = ""


@dataclass
class Filtry:
    lata: tuple[int, int] | None = None
    turniej: str | None = None
    rundy: list[str] = field(default_factory=list)
    nawierzchnia: str | None = None
    tura: str | None = None
    statystyki: bool = False  # pytanie o asy, serwis, break pointy, czas meczu...
    rekord: bool = False  # "najwięcej", "najdłuższy", "rekord"

    def opis(self) -> str:
        czesci = []
        if self.lata:
            czesci.append(f"rok {self.lata[0]}" if self.lata[0] == self.lata[1] else f"lata {self.lata[0]}–{self.lata[1]}")
        if self.turniej:
            czesci.append(f"turniej: {self.turniej}")
        if self.rundy:
            czesci.append("runda: " + ", ".join(RUNDY.get(r, r) for r in self.rundy))
        if self.nawierzchnia:
            czesci.append(f"nawierzchnia: {NAWIERZCHNIE.get(self.nawierzchnia, self.nawierzchnia)}")
        if self.tura:
            czesci.append(f"tour: {self.tura}")
        return ", ".join(czesci)

    def pusty(self) -> bool:
        return not (self.lata or self.turniej or self.rundy or self.nawierzchnia)

    def cokolwiek(self) -> bool:
        return not self.pusty() or self.statystyki or self.rekord

    def uzupelnij(self, stare: "Filtry") -> "Filtry":
        """Pytanie uzupełniające dziedziczy filtry poprzedniego, nowe wartości mają pierwszeństwo:
        „Kto wygrał Wimbledon 1985?” + „A w 1986?” = Wimbledon, 1986."""
        return Filtry(lata=self.lata or stare.lata, turniej=self.turniej or stare.turniej,
                      rundy=self.rundy or list(stare.rundy), nawierzchnia=self.nawierzchnia or stare.nawierzchnia,
                      tura=self.tura or stare.tura, statystyki=self.statystyki or stare.statystyki,
                      rekord=self.rekord)


@dataclass
class WynikMeczow:
    """Kontekst z bazy meczów dla jednego pytania."""

    rodzaj: str  # "h2h" | "kariera" | "turniej"
    tekst: str
    zawodnicy: list[str]
    filtry: Filtry
    liczba_meczow: int
    # jak zrozumiano pytanie uzupełniające, np. „Ile razy wygrał z Djokoviciem?” po pytaniu o Hurkacza
    doprecyzowanie: str = ""


# ============================================================================== baza
class BazaMeczow:
    def __init__(self, sciezka: Path, maks_meczow: int = 25):
        if not Path(sciezka).exists():
            raise FileNotFoundError(f"Brak bazy meczów {sciezka}. Utwórz ją: python -m narzedzia.pobierz_mecze")
        self.sciezka = Path(sciezka)
        self.maks = maks_meczow
        self.db = sqlite3.connect(str(sciezka), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        kolumny = {r[1] for r in self.db.execute("PRAGMA table_info(mecze)")}
        self.ma_statystyki = "punkty_serw_zw" in kolumny  # starsza baza (bez statystyk) też działa
        self.zawodnicy: list[Zawodnik] = []
        self._po_nazwisku: dict[str, list[Zawodnik]] = defaultdict(list)
        self._po_pelnej: dict[str, Zawodnik] = {}
        for w in self.db.execute("SELECT * FROM zawodnicy"):
            z = Zawodnik(w["nazwa"], w["tura"], w["kraj"] or "", w["mecze"], w["pierwszy_rok"], w["ostatni_rok"])
            z.norm_pelna = norm(z.nazwa)
            czlony = z.norm_pelna.split()
            z.nazwisko = czlony[-1] if czlony else ""
            z.imie = czlony[0] if len(czlony) > 1 else ""
            self.zawodnicy.append(z)
            self._po_nazwisku[z.nazwisko].append(z)
            self._po_pelnej.setdefault(z.norm_pelna, z)
            if len(czlony) >= 2:  # zapis odwrócony: "Li Na" / "Na Li"
                self._po_pelnej.setdefault(" ".join(reversed(czlony)), z)
        for lista in self._po_nazwisku.values():
            lista.sort(key=lambda z: -z.mecze)

    # ------------------------------------------------------------------ informacje
    def zakres(self) -> dict:
        w = self.db.execute("SELECT MIN(rok) od, MAX(rok) do_, COUNT(*) n FROM mecze").fetchone()
        tury = [r[0] for r in self.db.execute("SELECT DISTINCT tura FROM mecze ORDER BY tura")]
        return {"od": w["od"], "do": w["do_"], "mecze": w["n"], "tury": tury}

    def opis_zakresu(self) -> str:
        z = self.zakres()
        return f"{'/'.join(z['tury'])}, {z['od']}–{z['do']}, {z['mecze']:,} meczów".replace(",", " ")

    # ------------------------------------------------------------------ rozpoznawanie zawodników
    @staticmethod
    def _pasuje(token: str, nazwisko: str) -> bool:
        """Czy słowo z pytania to (odmienione) nazwisko?  nadala~nadal, sabalenki~sabalenka, radwanskiej~radwanska."""
        if len(nazwisko) < 3 or len(token) < 3:
            return False
        if token == nazwisko:
            return True
        if len(nazwisko) == 3:  # krótkie nazwiska (Lee, Ito) tylko przy dokładnej zgodności
            return False
        if token.startswith(nazwisko) and len(token) - len(nazwisko) <= 4:
            return True
        if nazwisko.endswith("a") and len(nazwisko) >= 4:
            rdzen = nazwisko[:-1]
            if token in (rdzen + "i", rdzen + "e", rdzen + "y", rdzen + "ie", rdzen + "iej", rdzen + "ej", rdzen + "a"):
                return True
            if nazwisko.endswith("ska") and token == nazwisko[:-1] + "iej":
                return True
        return False

    def _kandydaci(self, tok: str, tura: str | None) -> list[Zawodnik]:
        """Zawodnicy, których nazwisko pasuje do słowa (z odmianą i polskimi aliasami)."""
        for alias, cel in ALIASY.items():
            if tok.startswith(alias):
                tok = cel
                break
        for k in range(0, 5):
            rdzen = tok[: len(tok) - k] if k else tok
            if len(rdzen) < 3:
                break
            kandydaci = [z for nazwisko in (rdzen, rdzen + "a") for z in self._po_nazwisku.get(nazwisko, [])
                         if self._pasuje(tok, z.nazwisko) and (tura is None or z.tura == tura)]
            if kandydaci:
                return sorted(kandydaci, key=lambda z: -z.mecze)
        return []

    def znajdz_zawodnikow(self, pytanie: str, tura: str | None = None, maks: int = 2) -> list[Zawodnik]:
        tekst = norm(pytanie)
        zajete: list[tuple[int, int]] = []  # fragmenty pytania już "zużyte" (pełne nazwiska, nazwy turniejów)

        def wolne(a: int, b: int) -> bool:
            return all(b <= x or a >= y for x, y in zajete)

        # 0) nazwy turniejów nie są nazwiskami ("Puchar Davisa", "Indian Wells", "Billie Jean King Cup")
        for _, (_, wzorce) in TURNIEJE.items():
            for w in wzorce:
                for m in re.finditer(w, tekst):
                    zajete.append((m.start(), m.end()))
        for m in re.finditer(r"billie jean king cup|\bbjk cup|fed cup|rod laver arena|arthur ashe stadium", tekst):
            zajete.append((m.start(), m.end()))

        znalezieni: list[tuple[int, int, Zawodnik]] = []  # (pewność, pozycja, zawodnik)

        # 1) pełne imię i nazwisko w mianowniku ("novak djokovic") – najpewniejsze
        for pelna, z in self._po_pelnej.items():
            if len(pelna) >= 7 and " " in pelna and pelna in tekst and (tura is None or z.tura == tura):
                m = re.search(rf"\b{re.escape(pelna)}\b", tekst)
                if m and wolne(m.start(), m.end()):
                    znalezieni.append((3, m.start(), z))
                    zajete.append((m.start(), m.end()))

        # 2) nazwiska w dowolnej formie; imię tuż przed nazwiskiem ("Rafaela Nadala") podnosi pewność
        tokeny = [(m.start(), m.end(), m.group()) for m in re.finditer(r"[a-z]+", tekst)]
        dopasowania = []  # (indeks tokenu, zawodnik, pewnosc)
        for i, (a, b, tok) in enumerate(tokeny):
            if tok in NIE_NAZWISKA or len(tok) < 3 or not wolne(a, b):
                continue
            kandydaci = self._kandydaci(tok, tura)
            if not kandydaci:
                continue
            poprzedni = tokeny[i - 1][2] if i > 0 else ""
            z_imieniem_obok = [z for z in kandydaci if z.imie and self._pasuje(poprzedni, z.imie)]
            z_imieniem = z_imieniem_obok or [z for z in kandydaci if z.imie and any(self._pasuje(t, z.imie) for _, _, t in tokeny)]
            wybrany = (z_imieniem or kandydaci)[0]
            if wybrany.mecze >= 5 or z_imieniem:
                dopasowania.append((i, wybrany, 2 if z_imieniem_obok else 1))
        # imię zużyte przez pewne dopasowanie nie może być osobnym nazwiskiem ("Rafael" w "Rafaela Nadala")
        zuzyte_imiona = {i - 1 for i, _, pewnosc in dopasowania if pewnosc == 2}
        for i, z, pewnosc in dopasowania:
            if i in zuzyte_imiona:
                continue
            if all(z.nazwa != x.nazwa for _, _, x in znalezieni):
                znalezieni.append((pewnosc, tokeny[i][0], z))

        # najpierw najpewniejsze, potem w kolejności z pytania
        najlepsi = sorted(znalezieni, key=lambda x: (-x[0], x[1]))[:maks]
        return [z for _, _, z in sorted(najlepsi, key=lambda x: x[1])]

    # ------------------------------------------------------------------ filtry z pytania
    @staticmethod
    def wykryj_filtry(pytanie: str) -> Filtry:
        t = norm(pytanie)
        f = Filtry()
        lata = sorted({int(r) for r in re.findall(r"\b(19[2-9]\d|20[0-4]\d)\b", t)})
        if lata:
            f.lata = (lata[0], lata[-1])
        for nazwa, (_, wzorce) in TURNIEJE.items():
            if any(re.search(w, t) for w in wzorce):
                f.turniej = nazwa
                break
        if re.search(r"polfinal", t):
            f.rundy.append("SF")
        if re.search(r"cwiercfinal", t):
            f.rundy.append("QF")
        if re.search(r"(?<!pol)(?<!cwierc)\bfinal(?!s)", t) or re.search(r"\bw finale\b", t):
            f.rundy.append("F")
        if re.search(r"maczk|maczc|ziemn|\bclay", t):
            f.nawierzchnia = "Clay"
        elif re.search(r"\btraw|grass", t):
            f.nawierzchnia = "Grass"
        elif re.search(r"\btward|\bhard\b", t):
            f.nawierzchnia = "Hard"
        elif re.search(r"\bhal[iax]|dywan|carpet", t):
            f.nawierzchnia = "Carpet"
        f.statystyki = bool(re.search(_SLOWA_STATYSTYK, t))
        f.rekord = bool(re.search(r"najwiec\w*|najdluzsz\w*|najkrotsz\w*|rekord\w*|najszybsz\w*", t))
        if re.search(_SLOWA_KOBIETY, t):
            f.tura = "WTA"
        elif re.search(_SLOWA_MEZCZYZNI, t):
            f.tura = "ATP"
        return f

    # ------------------------------------------------------------------ SQL
    def _warunki(self, f: Filtry) -> tuple[list[str], list]:
        war, par = [], []
        if f.lata:
            war.append("rok BETWEEN ? AND ?")
            par += list(f.lata)
        if f.turniej:
            wzorce = TURNIEJE[f.turniej][0]
            war.append("(" + " OR ".join("turniej_norm LIKE ?" for _ in wzorce) + ")")
            par += [f"%{w}%" for w in wzorce]
            if f.turniej == "ATP/WTA Finals":
                war.append("poziom = 'F'")
        if f.rundy:
            war.append("runda IN (" + ",".join("?" * len(f.rundy)) + ")")
            par += f.rundy
        if f.nawierzchnia:
            war.append("nawierzchnia = ?")
            par.append(f.nawierzchnia)
        if f.tura:
            war.append("tura = ?")
            par.append(f.tura)
        return war, par

    def mecze(self, zawodnik: str | None = None, rywal: str | None = None, f: Filtry | None = None,
              limit: int | None = None) -> list[sqlite3.Row]:
        f = f or Filtry()
        war, par = self._warunki(f)
        if zawodnik and rywal:
            war.append("((zwyciezca = ? AND przegrany = ?) OR (zwyciezca = ? AND przegrany = ?))")
            par += [zawodnik, rywal, rywal, zawodnik]
        elif zawodnik:
            war.append("(zwyciezca = ? OR przegrany = ?)")
            par += [zawodnik, zawodnik]
        sql = "SELECT * FROM mecze" + (" WHERE " + " AND ".join(war) if war else "")
        sql += " ORDER BY data DESC, kolejnosc DESC" + (f" LIMIT {int(limit)}" if limit else "")
        return list(self.db.execute(sql, par))

    def szukaj_zawodnikow(self, fragment: str, tura: str | None = None, limit: int = 25) -> list[Zawodnik]:
        n = norm(fragment)
        if len(n) < 2:
            return []
        wynik = [z for z in self.zawodnicy if n in z.norm_pelna and (tura is None or z.tura == tura)]
        return sorted(wynik, key=lambda z: -z.mecze)[:limit]

    # ------------------------------------------------------------------ opisy dla modelu
    @staticmethod
    def linia_meczu(m: sqlite3.Row, perspektywa: str | None = None) -> str:
        runda = RUNDY.get(m["runda"], m["runda"] or "")
        wynik = f"{m['zwyciezca']} pokonał(a) {m['przegrany']} {m['wynik'] or ''}".strip()
        znak = ""
        if perspektywa:
            znak = "[W] " if m["zwyciezca"] == perspektywa else "[P] "
        czas = f" | {m['minuty'] // 60} h {m['minuty'] % 60:02d} min" if m["minuty"] else ""
        return (f"- {znak}{m['data']} | {m['turniej']} ({m['tura']}, {NAWIERZCHNIE.get(m['nawierzchnia'], m['nawierzchnia'] or '?')})"
                f" | {runda} | {wynik}{czas}")

    @staticmethod
    def _krotko(m: sqlite3.Row) -> str:
        """„Roland Garros 2025, półfinał – wygrał(a) Aryna Sabalenka 7-6(1) 4-6 6-0”."""
        return (f"{m['turniej']} {m['rok']}, {RUNDY.get(m['runda'], m['runda'] or '')} – wygrał(a) {m['zwyciezca']} "
                f"{m['wynik'] or ''}".strip())

    # ------------------------------------------------------------------ statystyki meczów
    def _ma_staty(self, m: sqlite3.Row) -> bool:
        return self.ma_statystyki and bool(m["punkty_serw_zw"]) and bool(m["punkty_serw_prz"])

    @staticmethod
    def _strona(m: sqlite3.Row, kto: str) -> tuple[str, str]:
        """Przyrostki kolumn: (zawodnik, rywal)."""
        return ("zw", "prz") if m["zwyciezca"] == kto else ("prz", "zw")

    @staticmethod
    def _proc(a: float, b: float) -> str:
        return f"{100 * a / b:.0f}%" if b else "–"

    def statystyki_meczu(self, m: sqlite3.Row) -> str | None:
        if not self._ma_staty(m):
            return None
        czesci = []
        for s, kto in (("zw", m["zwyciezca"]), ("prz", m["przegrany"])):
            sv, p1, w1, w2 = m[f"punkty_serw_{s}"], m[f"pierwszy_ok_{s}"] or 0, m[f"pierwszy_wyg_{s}"] or 0, m[f"drugi_wyg_{s}"] or 0
            bo, bb = m[f"bp_obronione_{s}"] or 0, m[f"bp_bronione_{s}"] or 0
            czesci.append(f"{kto}: asy {m[f'asy_{s}'] or 0}, podwójne błędy {m[f'podwojne_{s}'] or 0}, "
                          f"1. serwis {self._proc(p1, sv)}, pkt wygrane po 1. serwisie {self._proc(w1, p1)}, "
                          f"po 2. serwisie {self._proc(w2, sv - p1)}, obronione break pointy {bo}/{bb}")
        return "    statystyki – " + " | ".join(czesci)

    def statystyki_zbiorcze(self, mecze: list[sqlite3.Row], kto: str) -> str | None:
        """Średnie statystyki serwisu i returnu zawodnika w podanych meczach (tylko mecze z danymi)."""
        z_danymi = [m for m in mecze if self._ma_staty(m)]
        if not z_danymi:
            return None
        suma = defaultdict(float)
        for m in z_danymi:
            ja, on = self._strona(m, kto)
            for pole in ("asy", "podwojne", "punkty_serw", "pierwszy_ok", "pierwszy_wyg", "drugi_wyg", "gemy_serw",
                         "bp_obronione", "bp_bronione"):
                suma[pole] += m[f"{pole}_{ja}"] or 0
                suma["r_" + pole] += m[f"{pole}_{on}"] or 0
        n = len(z_danymi)
        przelamane = suma["bp_bronione"] - suma["bp_obronione"]
        przelamania = suma["r_bp_bronione"] - suma["r_bp_obronione"]
        return (
            f"Statystyki {kto} ({n} meczów z danymi): asy łącznie {int(suma['asy'])} (średnio {suma['asy'] / n:.1f} na mecz), "
            f"podwójne błędy łącznie {int(suma['podwojne'])} ({suma['podwojne'] / n:.1f} na mecz); 1. serwis {self._proc(suma['pierwszy_ok'], suma['punkty_serw'])}; "
            f"wygrane punkty po 1. serwisie {self._proc(suma['pierwszy_wyg'], suma['pierwszy_ok'])}, po 2. serwisie "
            f"{self._proc(suma['drugi_wyg'], suma['punkty_serw'] - suma['pierwszy_ok'])}; utrzymane gemy serwisowe "
            f"{self._proc(suma['gemy_serw'] - przelamane, suma['gemy_serw'])}; obronione break pointy "
            f"{self._proc(suma['bp_obronione'], suma['bp_bronione'])}; wygrane punkty na returnie "
            f"{self._proc(suma['r_punkty_serw'] - suma['r_pierwszy_wyg'] - suma['r_drugi_wyg'], suma['r_punkty_serw'])}; "
            f"wykorzystane break pointy {self._proc(przelamania, suma['r_bp_bronione'])} "
            f"({int(przelamania)}/{int(suma['r_bp_bronione'])})."
        )

    def _lista(self, mecze: list[sqlite3.Row], perspektywa: str | None, ze_statystykami: bool, limit: int) -> list[str]:
        linie = []
        for m in mecze[:limit]:
            linie.append(self.linia_meczu(m, perspektywa))
            if ze_statystykami:
                st = self.statystyki_meczu(m)
                if st:
                    linie.append(st)
        return linie

    @staticmethod
    def walkower(m: sqlite3.Row) -> bool:
        w = (m["wynik"] or "").strip().lower()
        return w in ("w/o", "walkover", "") or w.startswith("w/o")

    @classmethod
    def rozegrane(cls, mecze: list[sqlite3.Row]) -> list[sqlite3.Row]:
        """Bez walkowerów – oficjalne bilanse (head-to-head, wygrane–przegrane) liczą tylko mecze rozegrane."""
        return [m for m in mecze if not cls.walkower(m)]

    @staticmethod
    def _bilans(mecze: list[sqlite3.Row], kto: str) -> tuple[int, int]:
        w = sum(1 for m in mecze if m["zwyciezca"] == kto)
        return w, len(mecze) - w

    def _bilans_wg(self, mecze, kto, klucz, nazwy=None) -> str:
        grupy: dict[str, list] = defaultdict(list)
        for m in mecze:
            grupy[m[klucz] or "nieznana"].append(m)
        czesci = []
        for k, lista in sorted(grupy.items(), key=lambda x: -len(x[1])):
            w, p = self._bilans(lista, kto)
            czesci.append(f"{(nazwy or {}).get(k, k)} {w}–{p}")
        return "; ".join(czesci)

    def zestawienie_h2h(self, a: Zawodnik, b: Zawodnik, f: Filtry) -> WynikMeczow:
        z_walkowerami = self.mecze(a.nazwa, b.nazwa)
        wszystkie = self.rozegrane(z_walkowerami)
        wybrane = self.rozegrane(self.mecze(a.nazwa, b.nazwa, f)) if not f.pusty() else wszystkie
        wa, wb = self._bilans(wszystkie, a.nazwa)
        linie = [f"Bilans bezpośrednich meczów (head-to-head) {a.nazwa} – {b.nazwa} w całej bazie: "
                 f"{wa}–{wb} ({len(wszystkie)} rozegranych meczów). {a.nazwa} wygrał(a) {wa} z nich, "
                 f"{b.nazwa} wygrał(a) {wb}."]
        walkowery = [m for m in z_walkowerami if self.walkower(m)]
        if walkowery:
            linie.append("Nie liczono walkowerów (mecz nie został rozegrany): " + "; ".join(
                f"{m['turniej']} {m['rok']} – awans {m['zwyciezca']}" for m in walkowery) + ".")
        if wszystkie:
            linie.append(f"Według nawierzchni (wygrane–przegrane z perspektywy {a.nazwa}): "
                         + self._bilans_wg(wszystkie, a.nazwa, "nawierzchnia", NAWIERZCHNIE) + ".")
            szlemy = [m for m in wszystkie if m["poziom"] == "G"]
            if szlemy:
                w, p = self._bilans(szlemy, a.nazwa)
                linie.append(f"W turniejach wielkoszlemowych: {a.nazwa} {w}–{p}.")
            finaly = [m for m in wszystkie if m["runda"] == "F"]
            if finaly:
                w, p = self._bilans(finaly, a.nazwa)
                linie.append(f"W finałach: {a.nazwa} {w}–{p} ({len(finaly)} finałów).")
            pierwszy, ostatni = wszystkie[-1], wszystkie[0]
            linie.append(f"Pierwszy mecz: {self._krotko(pierwszy)}. Ostatni mecz: {self._krotko(ostatni)}.")
        if not f.pusty():
            w, p = self._bilans(wybrane, a.nazwa)
            linie.append(f"Mecze spełniające warunki pytania ({f.opis()}): {len(wybrane)}, bilans {a.nazwa} {w}–{p} "
                         f"({a.nazwa} wygrał(a) {w}, {b.nazwa} wygrał(a) {p}).")
            if wybrane:
                linie.append(f"Ostatni mecz spełniający warunki: {self._krotko(wybrane[0])}.")
        for kto in (a.nazwa, b.nazwa):
            st = self.statystyki_zbiorcze(wybrane, kto)
            if st:
                linie.append(st)
        ze_staty = f.statystyki or len(wybrane) <= 5
        limit = min(self.maks, 10) if ze_staty else self.maks
        linie.append(f"Lista meczów (od najnowszego, maks. {limit}; data = dzień rozpoczęcia turnieju):")
        linie += self._lista(wybrane, None, ze_staty, limit)
        if len(wybrane) > limit:
            linie.append(f"(… i {len(wybrane) - limit} wcześniejszych meczów)")
        return WynikMeczow("h2h", "\n".join(linie), [a.nazwa, b.nazwa], f, len(wybrane))

    def zestawienie_kariery(self, z: Zawodnik, f: Filtry) -> WynikMeczow:
        z_walkowerami = self.mecze(z.nazwa)
        # tytuł zdobyty walkowerem w finale liczy się (jak w oficjalnych statystykach), ale bilans – tylko mecze rozegrane
        tytuly = [m for m in z_walkowerami if m["runda"] == "F" and m["zwyciezca"] == z.nazwa
                  and not turniej_druzynowy(m["turniej"], m["poziom"])]
        wszystkie = self.rozegrane(z_walkowerami)
        w, p = self._bilans(wszystkie, z.nazwa)
        proc = 100 * w / max(len(wszystkie), 1)
        szlemy_tytuly = [m for m in tytuly if m["poziom"] == "G"]
        linie = [
            f"{z.nazwa} ({z.kraj}, {z.tura}) – rozegrane mecze w bazie: {len(wszystkie)} w latach {z.pierwszy_rok}–{z.ostatni_rok}; "
            f"bilans {w}–{p} ({proc:.1f}% zwycięstw).",
            f"Tytuły (wygrane finały turniejów głównego cyklu, bez rozgrywek drużynowych: Puchar Davisa, BJK Cup, "
            f"United Cup, ATP Cup, Laver Cup): {len(tytuly)}, "
            f"w tym wielkoszlemowe: {len(szlemy_tytuly)}.",
            "Bilans według nawierzchni: " + self._bilans_wg(wszystkie, z.nazwa, "nawierzchnia", NAWIERZCHNIE) + ".",
        ]
        szlemy = [m for m in wszystkie if m["poziom"] == "G"]
        if szlemy:
            sw, sp = self._bilans(szlemy, z.nazwa)
            linie.append(f"Bilans w Wielkim Szlemie: {sw}–{sp}; wg turnieju: " + self._bilans_wg(szlemy, z.nazwa, "turniej") + ".")
        lata_bilans = defaultdict(lambda: [0, 0])
        for m in wszystkie:
            lata_bilans[m["rok"]][0 if m["zwyciezca"] == z.nazwa else 1] += 1
        linie.append("Bilans rok po roku: " + "; ".join(f"{r}: {a}–{b}" for r, (a, b) in sorted(lata_bilans.items())) + ".")
        st = self.statystyki_zbiorcze(wszystkie, z.nazwa)
        if st:
            linie.append("Cała kariera – " + st)
        if f.pusty():
            linie.append("Ostatnie tytuły (maks. 15): " + "; ".join(f"{m['turniej']} {m['rok']}" for m in tytuly[:15]) + ".")
            wybrane = wszystkie[:10]
            linie.append("Ostatnie mecze w bazie:")
        else:
            wybrane = self.rozegrane(self.mecze(z.nazwa, None, f))
            fw, fp = self._bilans(wybrane, z.nazwa)
            linie.append(f"Mecze spełniające warunki pytania ({f.opis()}): {len(wybrane)}, bilans {fw}–{fp}.")
            st = self.statystyki_zbiorcze(wybrane, z.nazwa)
            if st:
                linie.append("W tych meczach – " + st)
            linie.append(f"Lista (od najnowszego, [W] wygrana, [P] porażka, maks. {self.maks}):")
        ze_staty = f.statystyki and len(wybrane) <= 15
        limit = min(self.maks, 10) if ze_staty else self.maks
        linie += self._lista(wybrane, z.nazwa, ze_staty, limit)
        if len(wybrane) > limit:
            linie.append(f"(… i {len(wybrane) - limit} kolejnych meczów)")
        return WynikMeczow("kariera", "\n".join(linie), [z.nazwa], f, len(wszystkie))

    def zestawienie_turnieju(self, f: Filtry) -> WynikMeczow | None:
        if not f.turniej:
            return None
        f2 = Filtry(lata=f.lata, turniej=f.turniej, rundy=f.rundy or ["F", "SF", "QF"], nawierzchnia=f.nawierzchnia, tura=f.tura)
        if not f.lata:
            f2.rundy = f.rundy or ["F"]  # bez roku: same finały (ostatnie lata)
        wybrane = self.mecze(None, None, f2)
        if not wybrane:
            return None
        linie = [f"Wyniki z bazy meczów ({f2.opis()}), od najnowszych:"]
        linie += self._lista(wybrane, None, f.statystyki, self.maks * 2)
        if len(wybrane) > self.maks * 2:
            linie.append(f"(… i {len(wybrane) - self.maks * 2} kolejnych)")
        return WynikMeczow("turniej", "\n".join(linie), [], f2, len(wybrane))

    @staticmethod
    def bez_wlasnego_podmiotu(pytanie: str) -> bool:
        """„A na trawie?”, „Ile tytułów zdobył?” – pytanie, które samo w sobie nie mówi, o kogo chodzi."""
        t = norm(pytanie)
        return wyglada_na_uzupelniajace(pytanie) or bool(
            re.search(_CZASOWNIKI_BEZ_PODMIOTU, t) and not re.search(r"\bkto\b", t))

    def jako_rywal(self, pytanie: str, z: Zawodnik) -> bool:
        """Czy zawodnik występuje w pytaniu jako rywal: „z Djokoviciem”, „przeciwko Sinnerowi”, „vs Alcaraz”."""
        for m in re.finditer(r"\b(?:z|ze|przeciw\w*|vs|kontra|versus)\s+((?:[a-z]+\s+)?[a-z]+)", norm(pytanie)):
            if any(x.nazwa == z.nazwa for x in self.znajdz_zawodnikow(m.group(1))):
                return True
        return False

    def kontekst(self, pytanie: str, poprzednie_pytanie: str | None = None) -> WynikMeczow | None:
        """Główna funkcja: pytanie -> zestawienie z bazy (albo None, jeśli pytanie nie dotyczy meczów).

        poprzednie_pytanie pozwala zrozumieć pytania uzupełniające, np. po „Bilans Nadala z Federerem?”
        pytanie „A z Djokoviciem?” oznacza bilans Nadal–Djoković, a „A na trawie?” – Nadal–Federer na trawie.
        Pytanie z własnym podmiotem („Ile tytułów zdobył Hurkacz?”) jest samodzielne – NIE łączymy go
        z zawodnikiem z poprzedniego pytania.
        """
        f = self.wykryj_filtry(pytanie)
        zawodnicy = self.znajdz_zawodnikow(pytanie, tura=None)
        t = norm(pytanie)
        slowa = len(pytanie.split())
        doprecyzowanie = ""
        if poprzednie_pytanie and len(zawodnicy) < 2 and slowa <= 8 and not re.search(
                r"w historii|wszech czasow|kiedykolwiek", t):
            poprzedni = self.znajdz_zawodnikow(poprzednie_pytanie, tura=None)
            f_poprz = self.wykryj_filtry(poprzednie_pytanie)
            nawiazuje = wyglada_na_uzupelniajace(pytanie)
            if len(zawodnicy) == 1:
                nowy = zawodnicy[0]
                if poprzedni and poprzedni[0].nazwa != nowy.nazwa and (
                        self.jako_rywal(pytanie, nowy) or (len(poprzedni) == 2 and nawiazuje and slowa <= 3)):
                    zawodnicy = [poprzedni[0], nowy]  # „A z Djokoviciem?”, „Ile razy wygrał z Federerem?”
                    doprecyzowanie = (f"pytanie dotyczy zawodnika z poprzedniego pytania ({poprzedni[0].nazwa}) "
                                      f"i jego/jej meczów z: {nowy.nazwa}")
                if nawiazuje and slowa <= 4:
                    f = f.uzupelnij(f_poprz)  # „A Karlović?” po „Ile asów zaserwował Isner w 2015?”
            elif poprzedni and (nawiazuje or ((f.cokolwiek() or re.search(_CZASOWNIKI_BEZ_PODMIOTU, t))
                                              and not re.search(r"\bkto\b", t))):
                # brak zawodnika: „A na trawie?”, „W finałach?”, „Ile razy wygrał Wimbledon?”, „Ile tytułów zdobył?”
                zawodnicy = poprzedni
                if not re.search(r"ogoln|w ogole|lacznie|calej karier|cala karier", t):
                    f = f.uzupelnij(f_poprz)
                doprecyzowanie = ("pytanie dotyczy zawodników z poprzedniego pytania: " if len(zawodnicy) > 1 else
                                  "pytanie dotyczy zawodnika z poprzedniego pytania: ") + " – ".join(z.nazwa for z in zawodnicy)
            elif not poprzedni and nawiazuje and not f_poprz.pusty():
                f = f.uzupelnij(f_poprz)  # „Kto wygrał Wimbledon 1985?” → „A w 1986?”
        if len(zawodnicy) >= 2:
            wynik = self.zestawienie_h2h(zawodnicy[0], zawodnicy[1], f)
        elif len(zawodnicy) == 1:
            f.tura = None  # tour wynika z zawodnika
            wynik = self.zestawienie_kariery(zawodnicy[0], f)
        elif f.rekord and (f.statystyki or re.search(r"mecz", t)):
            wynik = self.zestawienie_rekordow(pytanie, f)
        else:
            wynik = self.zestawienie_turnieju(f)
        if wynik is not None and doprecyzowanie:
            if not f.pusty():
                doprecyzowanie += f"; warunki: {f.opis()}"
            wynik.doprecyzowanie = doprecyzowanie
            wynik.tekst = f"Jak zrozumiano pytanie: {doprecyzowanie}.\n{wynik.tekst}"
        return wynik

    def zestawienie_rekordow(self, pytanie: str, f: Filtry) -> WynikMeczow | None:
        """Rekordy pojedynczych meczów: najwięcej asów, najdłuższe/najkrótsze mecze (z filtrami)."""
        t = norm(pytanie)
        war, par = self._warunki(f)
        gdzie = (" AND " + " AND ".join(war)) if war else ""
        if re.search(r"\bas(y|ow|ami|a)?\b|aces?", t):
            sql = (f"SELECT *, MAX(COALESCE(asy_zw,0), COALESCE(asy_prz,0)) AS wartosc FROM mecze "
                   f"WHERE asy_zw IS NOT NULL{gdzie} ORDER BY wartosc DESC LIMIT 10")
            opis = "Mecze z największą liczbą asów jednego zawodnika"
        elif re.search(r"podwojn", t):
            sql = (f"SELECT *, MAX(COALESCE(podwojne_zw,0), COALESCE(podwojne_prz,0)) AS wartosc FROM mecze "
                   f"WHERE podwojne_zw IS NOT NULL{gdzie} ORDER BY wartosc DESC LIMIT 10")
            opis = "Mecze z największą liczbą podwójnych błędów jednego zawodnika"
        elif re.search(r"najkrotsz", t):
            sql = f"SELECT *, minuty AS wartosc FROM mecze WHERE minuty >= 20{gdzie} ORDER BY minuty ASC LIMIT 10"
            opis = "Najkrótsze mecze (z zapisanym czasem gry, min. 20 minut)"
        elif re.search(r"najdluzsz|minut|trwal|czas", t):
            sql = f"SELECT *, minuty AS wartosc FROM mecze WHERE minuty IS NOT NULL{gdzie} ORDER BY minuty DESC LIMIT 10"
            opis = "Najdłuższe mecze (według zapisanego czasu gry)"
        else:
            return None
        wiersze = list(self.db.execute(sql, par))
        if not wiersze:
            return None
        linie = [f"{opis} w bazie meczów" + (f" ({f.opis()})" if not f.pusty() else "") +
                 " – dane o czasie i statystykach są od 1991 r. (ATP) i ok. 2007 r. (WTA):"]
        linie += self._lista(wiersze, None, True, 10)
        return WynikMeczow("rekordy", "\n".join(linie), [], f, len(wiersze))
