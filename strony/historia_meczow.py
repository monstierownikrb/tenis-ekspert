"""Przeglądarka pełnej historii meczów ATP i WTA (z bazy dane/mecze.sqlite)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from silnik.mecze import NAWIERZCHNIE, RUNDY, TURNIEJE, turniej_druzynowy
from strony.wspolne import INSTRUKCJA_BAZY_MECZOW, pobierz_baze_meczow, przygotuj_baze_meczow

st.title("📊 Historia meczów")

przygotuj_baze_meczow()  # w chmurze: pierwsza wizyta pobiera dane (lokalnie nic nie robi)
baza = pobierz_baze_meczow()
if baza is None:
    st.info(INSTRUKCJA_BAZY_MECZOW)
    st.stop()

zakres = baza.zakres()
st.caption(f"Baza: {baza.opis_zakresu()} · turnieje głównego cyklu · źródła: Jeff Sackmann / Tennis Abstract "
           "(CC BY-NC-SA 4.0) i tennis-data.co.uk")


def wybierz_zawodnika(etykieta: str, tura: str, klucz: str):
    fraza = st.text_input(etykieta, key=f"fraza_{klucz}", placeholder="wpisz fragment nazwiska, np. Hurkacz")
    if not fraza:
        return None
    kandydaci = baza.szukaj_zawodnikow(fraza, tura)
    if not kandydaci:
        st.warning(f"Nie znaleziono w rozgrywkach {tura} – sprawdź pisownię albo przełącz ATP/WTA.")
        return None
    return st.selectbox("Wybierz", kandydaci, key=f"wybor_{klucz}", label_visibility="collapsed",
                        format_func=lambda z: f"{z.nazwa} ({z.kraj or '?'}) · {z.mecze} meczów · {z.pierwszy_rok}–{z.ostatni_rok}")


# ----------------------------------------------------------------------------- filtry
k1, k2, k3 = st.columns([1, 2, 2])
tura = k1.radio("Tour", [t for t in ("ATP", "WTA") if t in zakres["tury"]], horizontal=True)
with k2:
    zawodnik = wybierz_zawodnika("Zawodnik / zawodniczka", tura, "a")
with k3:
    rywal = wybierz_zawodnika("Rywal (opcjonalnie – bilans head-to-head)", tura, "b")

f1, f2, f3, f4 = st.columns(4)
lata = f1.slider("Lata", zakres["od"], zakres["do"], (zakres["od"], zakres["do"]))
turniej = f2.selectbox("Turniej", ["(wszystkie)"] + list(TURNIEJE))
rundy = f3.multiselect("Runda", ["F", "SF", "QF", "R16", "R32", "R64", "R128", "RR"], format_func=lambda r: RUNDY.get(r, r))
nawierzchnie = f4.multiselect("Nawierzchnia", list(NAWIERZCHNIE), format_func=lambda n: NAWIERZCHNIE[n])
tylko_szlemy = st.checkbox("Tylko Wielki Szlem")

if not zawodnik and turniej == "(wszystkie)" and not rundy and not tylko_szlemy and lata == (zakres["od"], zakres["do"]):
    st.info("Wybierz zawodnika albo zawęź filtry (np. turniej i rundę „finał”), żeby zobaczyć mecze.")
    st.stop()

# ----------------------------------------------------------------------------- zapytanie SQL
war, par = ["tura = ?", "rok BETWEEN ? AND ?"], [tura, *lata]
if zawodnik and rywal:
    war.append("((zwyciezca = ? AND przegrany = ?) OR (zwyciezca = ? AND przegrany = ?))")
    par += [zawodnik.nazwa, rywal.nazwa, rywal.nazwa, zawodnik.nazwa]
elif zawodnik:
    war.append("(zwyciezca = ? OR przegrany = ?)")
    par += [zawodnik.nazwa, zawodnik.nazwa]
if turniej != "(wszystkie)":
    wzorce = TURNIEJE[turniej][0]
    war.append("(" + " OR ".join("turniej_norm LIKE ?" for _ in wzorce) + ")")
    par += [f"%{w}%" for w in wzorce]
if rundy:
    war.append(f"runda IN ({','.join('?' * len(rundy))})")
    par += rundy
if nawierzchnie:
    war.append(f"nawierzchnia IN ({','.join('?' * len(nawierzchnie))})")
    par += nawierzchnie
if tylko_szlemy:
    war.append("poziom = 'G'")

POLA_STAT = ["asy", "podwojne", "punkty_serw", "pierwszy_ok", "pierwszy_wyg", "drugi_wyg", "gemy_serw", "bp_obronione", "bp_bronione"]
kolumny_stat = [f"{p}_{s}" for p in POLA_STAT for s in ("zw", "prz")] if baza.ma_statystyki else ["asy_zw", "asy_prz", "podwojne_zw", "podwojne_prz"]
sql = (f"SELECT data, turniej, ranga, nawierzchnia, runda, zwyciezca, zwyciezca_kraj, przegrany, przegrany_kraj, wynik, "
       f"ranking_zw, ranking_prz, minuty, zrodlo, poziom, {', '.join(kolumny_stat)} FROM mecze WHERE {' AND '.join(war)} "
       f"ORDER BY data DESC, kolejnosc DESC LIMIT 20000")
df = pd.read_sql_query(sql, baza.db, params=par)

if df.empty:
    st.warning("Brak meczów spełniających warunki.")
    st.stop()

# ----------------------------------------------------------------------------- podsumowanie
walkower = df["wynik"].fillna("").str.strip().str.lower().str.startswith(("w/o", "walkover")) | (df["wynik"].fillna("").str.strip() == "")
if zawodnik:
    df.insert(0, "W/P", ["W" if z == zawodnik.nazwa else "P" for z in df["zwyciezca"]])
    druzynowe = [turniej_druzynowy(t, p) for t, p in zip(df["turniej"], df["poziom"])]
    tytuly = int(((df["runda"] == "F") & (df["W/P"] == "W") & ~pd.Series(druzynowe, index=df.index)).sum())
    rozegrane = df[~walkower]  # bilans jak w oficjalnych statystykach: bez walkowerów
    wygrane = int((rozegrane["W/P"] == "W").sum())
    przegrane = len(rozegrane) - wygrane
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Rozegrane mecze", len(rozegrane), help=f"Walkowery (nie liczone do bilansu): {int(walkower.sum())}")
    m2.metric("Bilans", f"{wygrane}–{przegrane}")
    m3.metric("Zwycięstwa", f"{100 * wygrane / max(len(rozegrane), 1):.1f}%")
    m4.metric("Wygrane finały" if not rywal else "Finały (wygrane)", tytuly)
    if rywal:
        st.subheader(f"{zawodnik.nazwa} – {rywal.nazwa}: {wygrane}–{przegrane}")

    t1, t2 = st.columns(2)
    with t1:
        st.markdown("**Bilans według nawierzchni**")
        wg = rozegrane.groupby("nawierzchnia")["W/P"].value_counts().unstack(fill_value=0)
        wg.index = [NAWIERZCHNIE.get(i, i) for i in wg.index]
        st.dataframe(wg.reindex(columns=["W", "P"], fill_value=0), width="stretch")
    with t2:
        st.markdown("**Bilans rok po roku**")
        lata_df = rozegrane.assign(rok=rozegrane["data"].str[:4])
        st.bar_chart(lata_df.groupby("rok")["W/P"].value_counts().unstack(fill_value=0).reindex(columns=["W", "P"], fill_value=0))
else:
    st.metric("Mecze", len(df))


def procent(a, b) -> str:
    return f"{100 * a / b:.1f}%" if b else "–"


# ----------------------------------------------------------------------------- statystyki serwisu i returnu
if zawodnik and baza.ma_statystyki:
    z_danymi = rozegrane[rozegrane["punkty_serw_zw"].notna() & rozegrane["punkty_serw_prz"].notna()]
    if len(z_danymi):
        ja = z_danymi["W/P"].map({"W": "zw", "P": "prz"})
        on = z_danymi["W/P"].map({"W": "prz", "P": "zw"})

        def kol(pole: str, strona) -> pd.Series:
            return pd.Series([z_danymi.iloc[i][f"{pole}_{strona.iloc[i]}"] for i in range(len(z_danymi))],
                             index=z_danymi.index).fillna(0).astype(float)

        S = {p: kol(p, ja) for p in POLA_STAT}
        R = {p: kol(p, on) for p in POLA_STAT}
        n = len(z_danymi)
        przelamany = S["bp_bronione"].sum() - S["bp_obronione"].sum()
        przelamania = R["bp_bronione"].sum() - R["bp_obronione"].sum()
        st.subheader(f"Statystyki serwisu i returnu – {zawodnik.nazwa}" + (f" przeciw {rywal.nazwa}" if rywal else ""))
        st.caption(f"Na podstawie {n} meczów ze statystykami (ATP od 1991 r., WTA od ok. 2007 r.).")
        a1, a2, a3, a4, a5 = st.columns(5)
        a1.metric("Asy na mecz", f"{S['asy'].sum() / n:.1f}", help=f"Łącznie: {int(S['asy'].sum())}")
        a2.metric("Podwójne błędy na mecz", f"{S['podwojne'].sum() / n:.1f}", help=f"Łącznie: {int(S['podwojne'].sum())}")
        a3.metric("1. serwis w korcie", procent(S["pierwszy_ok"].sum(), S["punkty_serw"].sum()))
        a4.metric("Pkt wygrane po 1. serwisie", procent(S["pierwszy_wyg"].sum(), S["pierwszy_ok"].sum()))
        a5.metric("Pkt wygrane po 2. serwisie", procent(S["drugi_wyg"].sum(), S["punkty_serw"].sum() - S["pierwszy_ok"].sum()))
        b1, b2, b3, b4, b5 = st.columns(5)
        b1.metric("Utrzymane gemy serwisowe", procent(S["gemy_serw"].sum() - przelamany, S["gemy_serw"].sum()))
        b2.metric("Obronione break pointy", procent(S["bp_obronione"].sum(), S["bp_bronione"].sum()))
        b3.metric("Pkt wygrane na returnie", procent(R["punkty_serw"].sum() - R["pierwszy_wyg"].sum() - R["drugi_wyg"].sum(), R["punkty_serw"].sum()))
        b4.metric("Wykorzystane break pointy", procent(przelamania, R["bp_bronione"].sum()), help=f"{int(przelamania)}/{int(R['bp_bronione'].sum())}")
        b5.metric("Średni czas meczu", f"{z_danymi['minuty'].dropna().mean():.0f} min" if z_danymi["minuty"].notna().any() else "–")

        rok = z_danymi["data"].str[:4]
        wykres = pd.DataFrame({
            "Asy na mecz": S["asy"].groupby(rok).mean(),
            "1. serwis %": (100 * S["pierwszy_ok"].groupby(rok).sum() / S["punkty_serw"].groupby(rok).sum()),
            "Pkt wygrane na returnie %": (100 * (R["punkty_serw"] - R["pierwszy_wyg"] - R["drugi_wyg"]).groupby(rok).sum()
                                          / R["punkty_serw"].groupby(rok).sum()),
        })
        miara = st.selectbox("Wykres rok po roku", list(wykres.columns))
        st.line_chart(wykres[[miara]])

# ----------------------------------------------------------------------------- tabela
def para(a, b, fmt="{:.0f}") -> str:
    return "" if pd.isna(a) or pd.isna(b) else f"{fmt.format(a)}–{fmt.format(b)}"


df["Asy (zw–prz)"] = [para(a, b) for a, b in zip(df["asy_zw"], df["asy_prz"])]
df["Podw. błędy (zw–prz)"] = [para(a, b) for a, b in zip(df["podwojne_zw"], df["podwojne_prz"])]
if baza.ma_statystyki:
    df["1. serwis % (zw–prz)"] = [para(100 * a / s1, 100 * b / s2) if s1 and s2 and not pd.isna(s1) and not pd.isna(s2) else ""
                                  for a, b, s1, s2 in zip(df["pierwszy_ok_zw"], df["pierwszy_ok_prz"], df["punkty_serw_zw"], df["punkty_serw_prz"])]
    df["Break pointy obronione (zw | prz)"] = [
        "" if pd.isna(a) else f"{a:.0f}/{b:.0f} | {c:.0f}/{d:.0f}"
        for a, b, c, d in zip(df["bp_obronione_zw"], df["bp_bronione_zw"], df["bp_obronione_prz"], df["bp_bronione_prz"])]
df = df.drop(columns=[c for c in kolumny_stat if c in df.columns])

pokaz = df.drop(columns=["poziom"]).rename(columns={
    "data": "Data", "turniej": "Turniej", "ranga": "Ranga", "nawierzchnia": "Nawierzchnia", "runda": "Runda",
    "zwyciezca": "Zwycięzca", "zwyciezca_kraj": "Kraj", "przegrany": "Przegrany", "przegrany_kraj": "Kraj ",
    "wynik": "Wynik", "ranking_zw": "Ranking zw.", "ranking_prz": "Ranking prz.", "minuty": "Minuty", "zrodlo": "Źródło"})
pokaz["Nawierzchnia"] = pokaz["Nawierzchnia"].map(lambda n: NAWIERZCHNIE.get(n, n))
pokaz["Runda"] = pokaz["Runda"].map(lambda r: RUNDY.get(r, r))
st.dataframe(pokaz, width="stretch", hide_index=True)
if len(df) == 20000:
    st.caption("Pokazano pierwsze 20 000 meczów – zawęź filtry.")
st.download_button("⬇️ Pobierz jako CSV", pokaz.to_csv(index=False).encode("utf-8-sig"),
                   file_name="mecze.csv", mime="text/csv")
