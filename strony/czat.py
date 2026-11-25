"""Strona czatu z Tenisowym Ekspertem."""
from __future__ import annotations

import hmac
from pathlib import Path

import streamlit as st

import config
from silnik import BladOllamy
from strony.wspolne import (pobierz_bota, pobierz_kolejke, przebuduj_indeks, przygotuj_baze_meczow,
                            przygotuj_indeks)

PRZYKLADOWE_PYTANIA = [
    "Kto wygrał Wimbledon w 1987 roku?",
    "Ile tytułów wielkoszlemowych ma Iga Świątek?",
    "Jak działa tie-break?",
    "Kto jest rekordzistą Roland Garros?",
    "Kto wygrał US Open 2026?",
    "Czym różni się mączka od trawy?",
    "Jaki jest bilans meczów Nadala z Federerem?",
    "Jak Hubert Hurkacz grał w 2023 roku?",
    "Kto wygrał Roland Garros 2026 wśród kobiet?",
]


def pokaz_dane_meczow(mecze: dict | None) -> None:
    if mecze:
        with st.expander(f"🗂️ Dane z bazy meczów ({mecze['liczba']} meczów)"):
            st.text(mecze["tekst"])


def pokaz_zrodla(trafienia: list[dict]) -> None:
    if not trafienia:
        return
    with st.expander(f"📚 Źródła ({len(trafienia)})"):
        for nr, t in enumerate(trafienia, 1):
            st.markdown(f"**[{nr}] {t['tytul']}**  \n`{t['zrodlo']}` · podobieństwo {t['podobienstwo']:.2f} · BM25 {t['bm25']:.1f}")
            st.caption(t["tekst"][:600] + ("…" if len(t["tekst"]) > 600 else ""))


# ======================================================================= start
st.title("🎾 Tenisowy Ekspert")
if config.W_CHMURZE:
    st.caption("Chatbot z bazą wiedzy o tenisie (RAG) i bazą 361 tys. meczów ATP/WTA. "
               "Odpowiedzi podaje z numerami źródeł i uczy się nowych faktów.")
else:
    st.caption("Chatbot na lokalnym modelu językowym (Ollama) z bazą wiedzy o tenisie (RAG). "
               "Odpowiedzi podaje z numerami źródeł.")
    if config.TRYB_PUBLICZNY:
        st.info("Wersja udostępniona w internecie: model Bielik działa na komputerze autora. "
                "Gdy pyta kilka osób naraz, odpowiedź może chwilę poczekać w kolejce.", icon="🌐")

if "wiadomosci" not in st.session_state:
    st.session_state.wiadomosci = []  # {"role", "content", "zrodla", "pytanie"}

try:
    przygotuj_baze_meczow()  # w chmurze: pierwsza wizyta pobiera dane (lokalnie nic nie robi)
    przygotuj_indeks()
    bot = pobierz_bota()
except BladOllamy as e:
    st.error(str(e))
    st.stop()
except FileNotFoundError:
    st.error("Brak indeksu bazy wiedzy. Zbuduj go poleceniem `python zbuduj_baze.py` albo przyciskiem poniżej.")
    if st.button("🔨 Zbuduj indeks teraz"):
        try:
            n = przebuduj_indeks()
            st.success(f"Zbudowano indeks: {n} fragmentów.")
            st.rerun()
        except BladOllamy as e:
            st.error(str(e))
    st.stop()
except ValueError as e:
    st.error(str(e))
    st.stop()

# ======================================================================= panel boczny
kolejka = pobierz_kolejke()
# Lokalnie autor ma wszystkie uprawnienia. W trybie publicznym (udostepnij.bat) – dopiero po wpisaniu hasła.
autor = not config.TRYB_PUBLICZNY or st.session_state.get("autor", False)

with st.sidebar:
    st.header("⚙️ Ustawienia")
    problemy = bot.klient.sprawdz()
    if problemy:
        for p in problemy:
            st.error(p)
    else:
        st.success("Model w chmurze odpowiada." if config.W_CHMURZE else "Ollama działa, modele są pobrane.")
    st.markdown(f"**Model:** `{config.MODEL_LLM}`" + (f" (API: {config.API_URL.split('/')[2]})" if config.W_CHMURZE else " (Ollama)")
                + f"  \n**Embeddingi:** `{config.MODEL_EMBED or 'brak – samo BM25'}`  \n"
                f"**Fragmentów w bazie:** {len(bot.indeks.fragmenty)}  \n"
                f"**Baza meczów:** {bot.baza_meczow.opis_zakresu() if bot.baza_meczow else 'brak (python -m narzedzia.pobierz_mecze)'}")
    uzyj_rag = st.toggle("Korzystaj z bazy wiedzy (RAG)", value=True,
                         help="Wyłącz, żeby porównać odpowiedzi samego modelu z odpowiedziami opartymi na bazie wiedzy.")
    top_k = st.slider("Liczba fragmentów w kontekście (top-k)", 2, 12, config.TOP_K)
    if st.button("🧹 Nowa rozmowa", width="stretch"):
        st.session_state.wiadomosci = []
        st.rerun()

    st.divider()
    st.header("🧠 Naucz bota")
    if not autor:
        st.caption("Twoja propozycja trafi do bazy wiedzy po zatwierdzeniu przez autora.")
    with st.form("naucz", clear_on_submit=True):
        fakt = st.text_area("Nowy fakt o tenisie", placeholder="np. Turniej ATP Finals 2026 wygrał ...")
        zrodlo = st.text_input("Źródło (opcjonalnie)", placeholder="np. atptour.com, 23.11.2026")
        if st.form_submit_button("Zapamiętaj" if autor else "Wyślij propozycję", width="stretch"):
            try:
                if autor:
                    bot.naucz(fakt, zrodlo or "użytkownik")
                    st.success("Zapamiętane – fakt jest już w bazie wiedzy.")
                else:
                    kolejka.dodaj(fakt, zrodlo or "gość")
                    st.success("Dziękuję! Fakt czeka na zatwierdzenie przez autora.")
            except (ValueError, BladOllamy) as e:
                st.error(str(e))

    if autor:
        plik = st.file_uploader("Wgraj dokument (.md, .txt, .pdf)", type=["md", "txt", "pdf"])
        if plik is not None and st.button("📥 Dodaj dokument do bazy", width="stretch"):
            config.KATALOG_WGRANE.mkdir(parents=True, exist_ok=True)
            cel = config.KATALOG_WGRANE / Path(plik.name).name
            cel.write_bytes(plik.getvalue())
            try:
                n = bot.wgraj_dokument(cel)
                st.success(f"Dodano {n} fragmentów z pliku {plik.name}.")
            except (ValueError, BladOllamy, RuntimeError) as e:
                st.error(str(e))

        st.divider()
        if st.button("🔨 Przebuduj cały indeks", width="stretch",
                     help="Użyj po ręcznej edycji plików w katalogu baza_wiedzy/"):
            try:
                n = przebuduj_indeks()
                st.success(f"Przebudowano indeks: {n} fragmentów.")
                st.rerun()
            except BladOllamy as e:
                st.error(str(e))

    plik_nauczone = config.KATALOG_NAUCZONE / "nauczone.md"
    if autor and config.W_CHMURZE and plik_nauczone.exists():
        st.download_button("⬇️ Pobierz nauczone fakty", plik_nauczone.read_bytes(), "nauczone.md", width="stretch",
                           help="Dysk serwera w chmurze jest tymczasowy. Żeby fakty zostały na stałe, "
                                "dodaj ten plik do repozytorium w folderze baza_wiedzy/nauczone/.")

    # ---- propozycje gości (widzi je autor)
    oczekujace = kolejka.lista() if autor else []
    if oczekujace:
        st.divider()
        st.header(f"📝 Do zatwierdzenia ({len(oczekujace)})")
        for w in oczekujace:
            with st.container(border=True):
                st.caption(f"{'Poprawka odpowiedzi' if w['rodzaj'] == 'poprawka' else 'Fakt'} · {w['czas'][:16].replace('T', ' ')}"
                           f" · źródło: {w['zrodlo']}")
                st.text(w["tekst"])
                k_tak, k_nie = st.columns(2)
                if k_tak.button("✅ Zatwierdź", key=f"tak_{w['id']}", width="stretch"):
                    wpis = kolejka.wyjmij(w["id"])
                    if wpis:
                        try:
                            bot.naucz(wpis["tekst"], f"{wpis['zrodlo']}, zatwierdzone przez autora")
                        except (ValueError, BladOllamy) as e:
                            st.error(str(e))
                    st.rerun()
                if k_nie.button("❌ Odrzuć", key=f"nie_{w['id']}", width="stretch"):
                    kolejka.wyjmij(w["id"])
                    st.rerun()

    # ---- logowanie autora (tylko w trybie publicznym)
    if config.TRYB_PUBLICZNY:
        st.divider()
        if autor:
            st.success("Jesteś zalogowany jako autor.")
            if st.button("Wyloguj", width="stretch"):
                st.session_state.autor = False
                st.rerun()
        else:
            with st.expander("🔒 Panel autora"):
                haslo = st.text_input("Hasło", type="password")
                if st.button("Zaloguj", width="stretch"):
                    if hmac.compare_digest(haslo.encode(), config.HASLO_ADMINA.encode()):
                        st.session_state.autor = True
                        st.rerun()
                    else:
                        st.error("Złe hasło.")

# ======================================================================= historia czatu
for i, w in enumerate(st.session_state.wiadomosci):
    with st.chat_message(w["role"], avatar="🎾" if w["role"] == "assistant" else None):
        st.markdown(w["content"])
        if w["role"] == "assistant":
            pokaz_dane_meczow(w.get("mecze"))
            pokaz_zrodla(w.get("zrodla", []))

# ocena ostatniej odpowiedzi
ostatnia = st.session_state.wiadomosci[-1] if st.session_state.wiadomosci else None
if ostatnia and ostatnia["role"] == "assistant" and not ostatnia.get("oceniona"):
    k1, k2, _ = st.columns([1, 1, 6])
    if k1.button("👍 Dobra odpowiedź"):
        bot.ocena(ostatnia["pytanie"], ostatnia["content"], dobra=True)
        ostatnia["oceniona"] = True
        st.rerun()
    if k2.button("👎 Zła odpowiedź"):
        st.session_state.poprawianie = True
    if st.session_state.get("poprawianie"):
        with st.form("poprawka"):
            poprawka = st.text_area("Jaka jest poprawna odpowiedź? Bot zapamięta ją na przyszłość."
                                    + ("" if autor else " (po zatwierdzeniu przez autora)"))
            if st.form_submit_button("Wyślij poprawkę"):
                try:
                    bot.ocena(ostatnia["pytanie"], ostatnia["content"], dobra=False, poprawka=poprawka, ucz=autor)
                    if autor:
                        st.success("Dzięki! Poprawka trafiła do bazy wiedzy.")
                    elif poprawka.strip():
                        kolejka.dodaj(f"Pytanie: {ostatnia['pytanie']}\nPoprawna odpowiedź: {poprawka.strip()}",
                                      "korekta gościa", rodzaj="poprawka")
                        st.success("Dzięki! Poprawka czeka na zatwierdzenie przez autora.")
                except (ValueError, BladOllamy) as e:
                    st.error(str(e))
                ostatnia["oceniona"] = True
                st.session_state.poprawianie = False
                st.rerun()

# przykładowe pytania na start
pytanie_z_przycisku = None
if not st.session_state.wiadomosci:
    st.markdown("**Przykładowe pytania:**")
    kolumny = st.columns(3)
    for i, p in enumerate(PRZYKLADOWE_PYTANIA):
        if kolumny[i % 3].button(p, width="stretch"):
            pytanie_z_przycisku = p

# ======================================================================= nowe pytanie
pytanie = st.chat_input("Zadaj pytanie o tenis...") or pytanie_z_przycisku
if pytanie:
    rozmowa = [{"role": w["role"], "content": w["content"]} for w in st.session_state.wiadomosci]
    with st.chat_message("user"):
        st.markdown(pytanie)
    with st.chat_message("assistant", avatar="🎾"):
        try:
            odp = bot.zapytaj(pytanie, rozmowa, uzyj_rag=uzyj_rag, top_k=top_k)
            tekst = st.write_stream(odp.strumien)
        except BladOllamy as e:
            st.error(str(e))
            st.stop()
        zrodla = [{"tytul": t.fragment.tytul, "zrodlo": t.fragment.zrodlo, "tekst": t.fragment.tekst,
                   "podobienstwo": t.podobienstwo, "bm25": t.bm25} for t in odp.trafienia]
        mecze = {"tekst": odp.mecze.tekst, "liczba": odp.mecze.liczba_meczow} if odp.mecze else None
        pokaz_dane_meczow(mecze)
        pokaz_zrodla(zrodla)
    st.session_state.wiadomosci += [
        {"role": "user", "content": pytanie},
        {"role": "assistant", "content": tekst if isinstance(tekst, str) else odp.tekst, "zrodla": zrodla,
         "mecze": mecze, "pytanie": pytanie},
    ]
    st.rerun()
