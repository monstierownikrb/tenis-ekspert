# 🎾 Tenisowy Ekspert – chatbot RAG na lokalnym modelu (Ollama)

Chatbot, który odpowiada na pytania o tenis: historię, zasady, turnieje, rekordy, zawodników, technikę i bieżący sezon.
Działa w całości **lokalnie**: polski model językowy **Bielik** uruchamiany przez **Ollamę** oraz własna baza wiedzy
(~830 fragmentów, w tym wszystkie finały Wielkiego Szlema 1968–2026) oraz **pełna historia meczów ATP i WTA**
(baza SQLite, kilkaset tysięcy meczów singlowych od 1968 roku). Bot **uczy się**: można mu dopisywać fakty,
wgrywać dokumenty i poprawiać złe odpowiedzi.

---

## 1. Jak to działa (w skrócie)

```
pytanie ──► [model embeddingów bge-m3] ──► wektor pytania
                                              │
baza_wiedzy/*.md ──► fragmenty ──► indeks ◄───┘  wyszukiwanie hybrydowe:
                                   (NumPy)       wektorowe (znaczenie) + BM25 (słowa, lata)
                                              │
                         6 najlepszych fragmentów (KONTEKST)
                                              │
pytanie ──► rozpoznanie zawodników i filtrów ──► SQL na bazie meczów ──► [M] bilanse, listy meczów
                                              │
pytanie + KONTEKST ([M] + fragmenty) + zasady ──► [LLM: Bielik 11B przez Ollamę] ──► odpowiedź ze źródłami [M], [1], [2]
```

**Dwa rodzaje wiedzy:** tekst (zasady, historia, biografie) wyszukujemy w bazie wiedzy, a **liczby o meczach**
(bilanse, wyniki, statystyki kariery) liczy dokładnie SQL na bazie meczów. Model językowy liczy źle, dlatego
dostaje gotowe wyniki i tylko je opisuje.

**Dlaczego tak, a nie sam model z poradnika?** Mały lokalny model „pamięta” tenis słabo i zmyśla daty oraz wyniki.
Dzięki RAG (Retrieval-Augmented Generation) model dostaje przed odpowiedzią fragmenty z bazy wiedzy i odpowiada na ich
podstawie, a nie z pamięci. Skrypt `ewaluacja.py` mierzy, ile to daje (odpowiedzi bez bazy vs z bazą).

---

## 2. Instalacja – Windows (komputer z RX 9070 XT) – ZALECANE

Każdy krok wykonujesz raz. Polecenia wpisujesz w **PowerShell** w folderze projektu.

1. **Zainstaluj Ollamę.** Pobierz instalator z https://ollama.com/download (Windows) i zainstaluj.
   Ollama uruchamia się w tle (ikonka lamy w zasobniku).
   *Karta RX 9070 XT działa w Ollamie na Windows przez Vulkan (włączony domyślnie) – nic nie trzeba konfigurować.*

2. **Zainstaluj Pythona 3.12** z https://www.python.org/downloads/ i podczas instalacji zaznacz **„Add python.exe to PATH”**.

3. **Rozpakuj projekt** (np. do `C:\projekty\tenis-chatbot`) i otwórz w tym folderze PowerShell
   (w Eksploratorze: Shift + prawy przycisk myszy → „Otwórz okno programu PowerShell tutaj”).

4. **Uruchom instalator projektu:**
   ```powershell
   .\instaluj.bat
   ```
   Skrypt robi kolejno: tworzy środowisko Pythona (`.venv`), instaluje biblioteki, pobiera modele
   `bge-m3` (~1,2 GB) i `Bielik 11B v3` (~7 GB), tworzy model `tenis-ekspert` z pliku `Modelfile`,
   buduje indeks bazy wiedzy i pobiera pełną historię meczów (~100 MB). Pobieranie modeli trwa najdłużej.

   <details><summary>To samo ręcznie, krok po kroku</summary>

   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\Activate.ps1          # jeśli błąd uprawnień: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
   pip install -r requirements.txt
   ollama pull bge-m3
   ollama pull SpeakLeash/bielik-11b-v3.0-instruct:Q4_K_M
   ollama create tenis-ekspert -f Modelfile
   python zbuduj_baze.py
   python -m narzedzia.pobierz_mecze
   ```
   </details>

5. **Uruchom chatbota:**
   ```powershell
   .\uruchom.bat
   ```
   Otworzy się przeglądarka z adresem http://localhost:8501.

6. **Sprawdź, czy model liczy na karcie graficznej:** w drugim oknie PowerShell wpisz `ollama ps` w trakcie odpowiedzi.
   W kolumnie `PROCESSOR` powinno być `100% GPU`. Jeśli widzisz `CPU`, zaktualizuj sterowniki AMD Adrenalin i Ollamę.

## 3. Instalacja – Ubuntu (laptop ThinkPad, bez mocnej karty)

```bash
curl -fsSL https://ollama.com/install.sh | sh     # instalacja Ollamy
sudo apt install python3-venv                     # jeśli brak
bash instaluj.sh laptop                           # wersja lekka: Bielik 4.5B (Modelfile.laptop)
bash uruchom.sh
```
`bash` przed nazwą skryptu działa także wtedy, gdy pliki skopiowane z pendrive'a straciły prawo do uruchamiania.
Pierwsze liczenie embeddingów na samym procesorze trwa ok. 15–20 minut; kolejne przebudowy indeksu liczą tylko
nowe i zmienione fragmenty (`python zbuduj_baze.py --od-nowa` liczy wszystko od zera).
Na samym procesorze odpowiedź generuje się wolniej (kilka–kilkanaście sekund). Na prezentację lepiej użyć komputera z RX 9070 XT.

## 4. Zgodność z poradnikiem z zajęć (Hugging Face → Ollama)

Model Bielik jest też na Hugging Face w formacie GGUF, więc możesz pobrać go dokładnie tak, jak w poradniku:
wejdź na `huggingface.co/speakleash/Bielik-11B-v3.0-Instruct-GGUF` → **Use this model** → **Ollama** → wybierz kwantyzację
**Q4_K_M** (plik ~7 GB, czyli o kilka GB mniej niż 16 GB VRAM karty) → skopiuj polecenie `ollama run hf.co/...`.
Następnie w pliku `Modelfile` podmień linię `FROM ...` na skopiowaną nazwę (`hf.co/...`) i wykonaj
`ollama create tenis-ekspert -f Modelfile`. Reszta projektu działa bez zmian.

---

## 5. Pełna historia meczów (ATP i WTA od 1968 roku)

Instalator robi to automatycznie (krok 6). Ręcznie / do aktualizacji:
```powershell
python -m narzedzia.pobierz_mecze                 # ATP + WTA, 1968 – dziś (ok. 100 MB, kilka minut)
python -m narzedzia.pobierz_mecze --od 2000       # krócej
python -m narzedzia.pobierz_mecze --challengery   # + challengery i kwalifikacje ATP
```
**Skąd dane:**
- **1968 – maj 2026** – baza Jeffa Sackmanna (Tennis Abstract): wszystkie mecze singlowe turniejów głównego cyklu
  (Wielki Szlem, Masters, ATP/WTA 250–500, finały sezonu, igrzyska, Puchar Davisa/BJK Cup), z wynikiem, rundą,
  nawierzchnią, rankingami i (od lat 90.) statystykami serwisu – ok. 360 tys. meczów. Oryginalne repozytoria
  Sackmanna zniknęły z GitHuba jesienią 2026, więc skrypt pobiera dane z archiwalnej kopii
  `Aneeshers/tennis-sackmann-archive` (GitHub, zapasowo Hugging Face). Licencja CC BY-NC-SA 4.0 – wolno używać
  niekomercyjnie, z podaniem autora (zrób to w sprawozdaniu). Kopia kończy się na Roland Garros 2026.
- **Później (opcjonalnie)** – skrypt próbuje dociągnąć nowsze mecze z tennis-data.co.uk. Jeśli to się nie uda,
  wyniki z drugiej połowy 2026 roku są w bazie wiedzy (pliki o sezonie i finałach Wielkiego Szlema), a nowe możesz
  dopisać funkcją „Naucz bota”.
- **Statystyki meczów** – asy, podwójne błędy, 1. serwis, punkty wygrane po 1. i 2. serwisie, break pointy, czas meczu:
  ATP od 1991 r., WTA od ok. 2007 r. (ok. 70–98% meczów). Skrypt odrzuca oczywiste błędy źródła (np. mecz 6:4, 6:2
  „trwający 41 godzin”). Czat odpowiada na pytania typu „Ile asów zaserwował Hurkacz w 2023?”, „Statystyki finału
  Wimbledonu 2019”, „Kto zaserwował najwięcej asów w jednym meczu?”, a zakładka „Historia meczów” pokazuje średnie
  serwisu/returnu zawodnika, wykres rok po roku i statystyki każdego meczu w tabeli.
- **Walkowery** (wygrane bez gry) są w bazie, ale nie liczą się do bilansów – tak jak w oficjalnych statystykach
  (np. Nadal–Federer 24–16). Finał wygrany walkowerem liczy się jako tytuł.

Skrypt pobiera pliki do `dane_zrodlowe/mecze/` i buduje bazę `dane/mecze.sqlite`. **Aktualizacja:** uruchom go
ponownie (np. raz w tygodniu) – pobierze tylko bieżący sezon. Jeśli sieć blokuje pobieranie (np. na uczelni),
pobierz pliki ręcznie, wrzuć do `dane_zrodlowe/mecze/sackmann/` lub `.../tennis_data/` (nazwy jak `atp_2025.xlsx`)
i uruchom `python -m narzedzia.pobierz_mecze --bez-pobierania`.

**Jak z tego korzystać:**
- **W czacie** – po prostu pytaj: „Jaki jest bilans Nadala z Federerem?”, „Jak Hurkacz grał w 2023 roku?”,
  „Mecze Świątek z Sabalenką na mączce”, „Kto grał w półfinałach Wimbledonu 2008?”, a potem dopytuj: „A na trawie?”,
  „A z Djokoviciem?”. Bot rozpoznaje nazwiska w odmianie (Nadala, Djokovicia, Sabalenki, Radwańskiej) i polskie
  zapisy (Dżoković, Miedwiediew). Dane, na których oparł odpowiedź, są w rozwijanym polu „🗂️ Dane z bazy meczów”.
- **Zakładka „📊 Historia meczów”** – przeglądarka wszystkich meczów: wybierz zawodnika (i opcjonalnie rywala),
  lata, turniej, rundę, nawierzchnię. Zobaczysz bilans, statystyki według nawierzchni i lat, tabelę meczów
  i możesz ją pobrać jako CSV (np. do wykresów w sprawozdaniu).

## 6. Korzystanie

- **Interfejs WWW:** `streamlit run app.py` (albo `uruchom.bat`). Pod każdą odpowiedzią są rozwijane **źródła**.
  W panelu bocznym możesz wyłączyć bazę wiedzy (przełącznik RAG), żeby pokazać różnicę na żywo.
- **Terminal:** `python czat.py` – polecenia `/naucz <fakt>`, `/zrodla`, `/rag`, `/nowa`, `/wyjdz`.
- **Bezpośrednio model (bez bazy wiedzy):** `ollama run tenis-ekspert`.

### Udostępnianie w internecie (strona dla wszystkich)

Komputer z kartą graficzną działa jako serwer, a reszta osób (prowadzący, laptop, telefon) tylko otwiera link
w przeglądarce. Model Bielik 11B nadal liczy się lokalnie – na karcie RX 9070 XT – więc odpowiedzi są tak dobre
i szybkie jak na komputerze.

1. Uruchom **`udostepnij.bat`**. Za pierwszym razem zainstaluje program `cloudflared` (bezpłatny, bez konta).
2. Ustaw hasło autora. W oknie pojawi się adres w ramce, np. `https://cos-tam.trycloudflare.com` – wyślij go.
3. Adres działa, dopóki komputer jest włączony, a oba okna (serwer i tunel) są otwarte. Każde uruchomienie daje
   **nowy** adres.

W trybie publicznym każdy może rozmawiać z chatbotem i przeglądać historię meczów. Fakty z „Naucz bota” i poprawki
po 👎 od gości trafiają do kolejki (`logi/do_zatwierdzenia.json`); autor po zalogowaniu w **„🔒 Panel autora”**
zatwierdza je (✅) albo odrzuca (❌). Wgrywanie dokumentów i przebudowa indeksu są dostępne tylko dla autora.
Ollama nie jest wystawiana do internetu – tunel prowadzi wyłącznie do strony (port 8501).

### Wersja na stronę internetową (Streamlit Community Cloud) – bez własnego komputera

Aplikacja działa na darmowym serwerze Streamlit pod stałym adresem `https://<nazwa>.streamlit.app`.
Serwer nie ma karty graficznej, więc zamiast Ollamy model językowy jest wołany przez **API zgodne z OpenAI**
(domyślnie Mistral – darmowy plan „Free mode”, dobrze zna polski; embeddingi: `mistral-embed`).
Reszta – baza wiedzy, wyszukiwanie hybrydowe, baza 361 tys. meczów, uczenie się – działa tak samo.

1. **Klucz API:** załóż konto na https://console.mistral.ai (wymaga weryfikacji numeru telefonu), w „API Keys”
   utwórz klucz. W panelu administracyjnym możesz wyłączyć używanie danych do trenowania modeli.
2. **GitHub:** załóż repozytorium (może być publiczne) i wgraj do niego pliki projektu **bez** folderów `.venv`,
   `dane`, `indeks`, `logi` (najprościej: rozpakuj ZIP projektu i przeciągnij pliki na stronę repozytorium
   → „uploading an existing file”).
3. **Hosting:** wejdź na https://share.streamlit.io, zaloguj się przez GitHub → „Create app” → wybierz repozytorium,
   gałąź `main`, plik `app.py`, w „Advanced settings” wybierz Python 3.12 i wklej w „Secrets”:
   ```toml
   LLM_DOSTAWCA = "api"
   API_URL = "https://api.mistral.ai/v1"
   API_KLUCZ = "tu-wklej-klucz"
   MODEL_LLM = "mistral-small-latest"
   MODEL_EMBED = "mistral-embed"
   TENIS_HASLO = "haslo-autora"
   ```
4. **Deploy.** Pierwsza wizyta po każdym uruchomieniu serwera trwa ok. 1–2 minut: aplikacja sama pobiera
   historię meczów (budowa bazy zużywa ok. 110 MB RAM) i liczy embeddingi bazy wiedzy przez API.

Uwagi: darmowa aplikacja zasypia po kilku godzinach bez ruchu – przed prezentacją otwórz link kilka minut wcześniej.
Dysk serwera jest tymczasowy: fakty zatwierdzone w aplikacji znikną po restarcie, dlatego autor ma przycisk
„⬇️ Pobierz nauczone fakty” – plik `nauczone.md` wrzuć do repozytorium w `baza_wiedzy/nauczone/`.
Inny dostawca = inne `API_URL` i nazwy modeli, np. Bielik przez PLGrid/Cyfronet (`https://llmlab.plgrid.pl/api/v1`,
wymaga konta PLGrid) – wtedy `MODEL_EMBED = ""` oznacza wyszukiwanie tylko po słowach (BM25).

## 7. Jak bot się uczy (wymaganie „chatbot uczący się”)

| Sposób | Gdzie | Co się dzieje |
|---|---|---|
| **Naucz bota** – wpisanie nowego faktu | panel boczny / `/naucz` w terminalu | fakt trafia do `baza_wiedzy/nauczone/nauczone.md` i od razu do indeksu |
| **Wgranie dokumentu** (.md, .txt, .pdf) | panel boczny | dokument jest dzielony na fragmenty i dodawany do indeksu |
| **Ocena 👎 + poprawka** | pod odpowiedzią | poprawna odpowiedź zapisuje się jako nowy fakt |
| **Pobranie artykułów z Wikipedii** | `python -m narzedzia.pobierz_wikipedia` | zapisuje hasła do `baza_wiedzy/wikipedia/`, potem `python zbuduj_baze.py` |
| **Ręczna edycja bazy** | pliki w `baza_wiedzy/` | po zmianach: przycisk „Przebuduj cały indeks” albo `python zbuduj_baze.py` |

Wszystkie rozmowy, oceny i nauczone fakty są logowane w `logi/` (pliki `.jsonl`) – przydatne do sprawozdania.

## 8. Ewaluacja – liczby do sprawozdania

```powershell
python ewaluacja.py                      # 38 pytań: wyszukiwanie + odpowiedzi bez RAG i z RAG
python ewaluacja.py --tylko-wyszukiwanie # szybko, bez LLM-a
```
Raport w Markdown (tabela + wszystkie odpowiedzi) zapisuje się w `wyniki/`. Pytania i oczekiwane słowa kluczowe są w
`testy/pytania_testowe.json` – możesz dopisać własne. Testy jednostkowe kodu: `python -m pytest testy -q`.

---

## 9. Struktura projektu

```
tenis-chatbot/
├── app.py                  interfejs WWW (Streamlit) – nawigacja między stronami
├── strony/                 czat.py, historia_meczow.py, wspolne.py
├── czat.py                 czat w terminalu
├── udostepnij.bat          udostępnienie strony w internecie (tunel Cloudflare, tryb publiczny)
├── zbuduj_baze.py          budowa indeksu (embeddingi całej bazy)
├── ewaluacja.py            pomiar jakości (bez RAG vs z RAG)
├── config.py               ustawienia (modele, top-k, temperatura, ścieżki)
├── Modelfile               model "tenis-ekspert" = Bielik 11B + parametry + prompt (PC z GPU)
├── Modelfile.laptop        wersja lekka – Bielik 4.5B (laptop/CPU)
├── silnik/
│   ├── tekst.py            normalizacja, tokeny BM25, dzielenie na fragmenty
│   ├── indeks.py           baza wektorowa (NumPy) + BM25 + fuzja RRF
│   ├── ollama_klient.py    komunikacja z Ollamą, czytelne błędy
│   ├── api_klient.py       model w chmurze przez API zgodne z OpenAI (Mistral, Gemini, PLGrid…)
│   ├── mecze.py            baza meczów: rozpoznawanie nazwisk, filtry, bilanse (SQL)
│   ├── kolejka.py          propozycje faktów od gości czekające na zatwierdzenie
│   └── chatbot.py          RAG, prompt, uczenie się, oceny, logi
├── baza_wiedzy/            WIEDZA BOTA (Markdown) – można edytować i dopisywać
│   ├── 01_zasady_gry.md … 10_sezon_2025_2026.md
│   ├── zawodnicy/          biografie zawodników i zawodniczek
│   ├── wielki_szlem/       wygenerowane z CSV: 468 finałów, statystyki, rekordziści
│   └── nauczone/           fakty dodane przez użytkowników (tworzy się samo)
├── dane_zrodlowe/finaly_wielkiego_szlema.csv
├── narzedzia/
│   ├── generuj_szlemy.py   CSV → pliki Markdown ze statystykami
│   ├── pobierz_mecze.py    pełna historia meczów → dane/mecze.sqlite
│   └── pobierz_wikipedia.py
├── dane/mecze.sqlite       baza meczów (tworzy się po uruchomieniu pobierz_mecze)
└── testy/                  testy jednostkowe, atrapa Ollamy, pytania testowe
```

## 10. Najważniejsze pojęcia (na obronę projektu)

- **LLM (Bielik 11B v3)** – polski model językowy od SpeakLeash. Format **GGUF** to skompresowany zapis wag dla Ollamy,
  a **kwantyzacja Q4_K_M** oznacza ~4 bity na wagę: model zajmuje ~7 GB zamiast ~22 GB, kosztem niewielkiej utraty jakości.
- **Embedding** – zamiana tekstu na wektor liczb (tu 1024 liczby z modelu `bge-m3`). Teksty o podobnym znaczeniu mają
  podobne wektory, co mierzymy **podobieństwem cosinusowym**.
- **BM25** – klasyczny algorytm wyszukiwania po słowach kluczowych. Uzupełnia embeddingi tam, gdzie liczą się dokładne
  słowa i liczby („Wimbledon 1987”). Wyniki obu metod łączy **Reciprocal Rank Fusion**.
- **RAG** – model odpowiada na podstawie wyszukanych fragmentów i podaje ich numery, więc odpowiedź da się sprawdzić.
- **Temperatura 0,2** – mała losowość generowania = mniej zmyślania. **num_ctx 8192** – ile tokenów model „widzi” naraz.
- **Dane strukturalne + SQL** – liczby (bilanse, wyniki) liczy baza danych, a nie model. To podejście łączące RAG
  z „narzędziem” obliczeniowym ogranicza halucynacje przy pytaniach statystycznych.
- **Uczenie się** – nie zmieniamy wag modelu (fine-tuning wymagałby mocnego GPU i danych treningowych), tylko
  rozbudowujemy bazę wiedzy w trakcie działania. Nowa wiedza działa natychmiast i nie „psuje” modelu.

## 11. Rozwiązywanie problemów

| Problem | Przyczyna i rozwiązanie |
|---|---|
| „Nie mogę połączyć się z Ollamą” | Ollama nie działa – uruchom aplikację Ollama (albo `ollama serve`). |
| „Ollama nie ma modelu …” | Model nie jest pobrany: `ollama pull bge-m3` / `ollama create tenis-ekspert -f Modelfile`. |
| „Brak indeksu” | Nie zbudowano bazy: `python zbuduj_baze.py`. |
| „Wymiar wektorów indeksu nie pasuje” / „zbudowano modelem …” | Zmieniono model embeddingów – przebuduj indeks. |
| Odpowiedzi bardzo wolne | Model liczy na CPU (`ollama ps`). Na laptopie użyj `Modelfile.laptop` albo zmniejsz `NUM_CTX`. |
| Bot mówi „Nie mam tej informacji” | Tak ma być, gdy w bazie nie ma faktu. Dopisz go funkcją „Naucz bota”. |
| PowerShell nie pozwala uruchomić `Activate.ps1` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| „Baza meczów: brak” | Nie utworzono bazy: `python -m narzedzia.pobierz_mecze`, potem odśwież aplikację. |
| Pobieranie meczów: same „brak” | Źródło zmieniło adres. Pobierz pliki `atp/atp_matches_*.csv` i `wta/wta_matches_*.csv` z kopii `Aneeshers/tennis-sackmann-archive` ręcznie do `dane_zrodlowe/mecze/sackmann/` i użyj `--bez-pobierania`. |
| Pobieranie meczów: „blad: …” | Sieć blokuje GitHub – j.w. (ręczne pobranie + `--bez-pobierania`). „tennis-data … niedostępne” możesz zignorować. |
| Bot nie rozpoznał zawodnika | Wpisz imię i nazwisko (np. „Iga Świątek”) albo sprawdź pisownię w zakładce „Historia meczów”. |
| Bilans różni się od oficjalnego | Baza obejmuje turnieje głównego cyklu; oficjalne statystyki bywają liczone nieco inaczej. |

Zmiana modelu bez edycji plików: `$env:MODEL_LLM = "SpeakLeash/bielik-4.5b-v3.0-instruct:Q8_0"` (PowerShell)
albo `export MODEL_LLM=...` (bash), a potem uruchom aplikację w tym samym oknie.

## 12. Źródła danych

Baza meczów: Jeff Sackmann / Tennis Abstract (CC BY-NC-SA 4.0), pobierane z archiwalnej kopii
github.com/Aneeshers/tennis-sackmann-archive (oryginał: github.com/JeffSackmann/tennis_atp i tennis_wta);
opcjonalne uzupełnienie: tennis-data.co.uk.
Finały Wielkiego Szlema 1968–2025: listy mistrzów na Wikipedii (angielskiej), uzupełnione o wyniki 2026 roku z oficjalnych
serwisów turniejów i agencji prasowych. Pozostałe pliki bazy wiedzy to opracowanie własne. Dane bieżące (rankingi, sezon 2026)
są aktualne na **17 listopada 2026** – ATP Finals 2026 trwały wtedy jeszcze; wynik możesz dopisać funkcją „Naucz bota”.
