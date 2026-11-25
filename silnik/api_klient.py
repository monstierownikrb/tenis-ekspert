"""Klient modeli językowych w chmurze przez API zgodne z OpenAI (/chat/completions, /embeddings).

Dzięki temu ten sam chatbot działa bez Ollamy – np. na darmowym hostingu Streamlit Community Cloud.
Pasuje do każdego dostawcy z API w standardzie OpenAI, m.in.:
  - Mistral AI          https://api.mistral.ai/v1                                  (czat + embeddingi)
  - Google Gemini       https://generativelanguage.googleapis.com/v1beta/openai    (czat + embeddingi)
  - Groq                https://api.groq.com/openai/v1                             (sam czat)
  - PLGrid / Cyfronet   https://llmlab.plgrid.pl/api/v1                            (Bielik przez API)
Ma ten sam zestaw metod co KlientOllama, więc reszta kodu nie musi wiedzieć, z którego korzysta.
"""
from __future__ import annotations

import json
import time
from typing import Iterator, Sequence

import httpx

from .ollama_klient import BladOllamy


class KlientAPI:
    def __init__(self, url: str, klucz: str, model_llm: str, model_embed: str, temperatura: float = 0.2,
                 maks_tokenow: int = 1024, limit_czasu: float = 120.0):
        self.host = url.rstrip("/")
        self.model_llm = model_llm
        self.model_embed = model_embed
        self.temperatura = temperatura
        self.maks_tokenow = maks_tokenow
        self._klucz = klucz
        self._http = httpx.Client(timeout=httpx.Timeout(limit_czasu, connect=15.0),
                                  headers={"Authorization": f"Bearer {klucz}"} if klucz else {})
        self._sprawdzone: tuple[float, list[str]] | None = None

    # ---------------------------------------------------------------- pomocnicze
    def _blad(self, e: Exception | None, odp: httpx.Response | None = None) -> BladOllamy:
        if odp is not None:
            kod = odp.status_code
            try:
                szczegoly = odp.json()
            except ValueError:
                szczegoly = odp.text[:300]
            if kod == 401:
                return BladOllamy("Klucz API jest nieprawidłowy albo wygasł – sprawdź API_KLUCZ w ustawieniach (Secrets).")
            if kod == 429:
                return BladOllamy("Darmowy limit zapytań do modelu jest chwilowo wyczerpany – spróbuj za chwilę.")
            if kod == 404:
                return BladOllamy(f"Dostawca API nie zna modelu (czat: '{self.model_llm}', embeddingi: "
                                  f"'{self.model_embed}') – sprawdź MODEL_LLM i MODEL_EMBED. Szczegóły: {szczegoly}")
            return BladOllamy(f"Błąd API modelu (HTTP {kod}): {szczegoly}")
        return BladOllamy(f"Nie mogę połączyć się z API modelu ({self.host}): {e}")

    def _post(self, sciezka: str, dane: dict, proby: int = 4) -> httpx.Response:
        """POST z ponowieniem przy limicie zapytań (429) i chwilowych błędach serwera (5xx).
        Darmowe plany pozwalają np. na 1 zapytanie na sekundę, więc krótkie odczekanie zwykle wystarcza."""
        for proba in range(proby):
            try:
                odp = self._http.post(f"{self.host}{sciezka}", json=dane)
            except httpx.HTTPError as e:
                if proba == proby - 1:
                    raise self._blad(e) from e
                time.sleep(1.5 * (proba + 1))
                continue
            if odp.status_code == 429 or odp.status_code >= 500:
                if proba == proby - 1:
                    raise self._blad(None, odp)
                czekaj = odp.headers.get("retry-after")
                time.sleep(float(czekaj) if czekaj and czekaj.replace(".", "", 1).isdigit() else 1.5 * (proba + 1))
                continue
            if odp.status_code >= 400:
                raise self._blad(None, odp)
            return odp
        raise AssertionError("nieosiągalne")

    # ---------------------------------------------------------------- embeddingi
    def embed(self, teksty: Sequence[str]) -> list[list[float]]:
        if not self.model_embed:
            raise BladOllamy("Nie ustawiono modelu embeddingów (MODEL_EMBED).")
        wektory: list[list[float]] = []
        teksty = list(teksty)
        for i in range(0, len(teksty), 16):  # małe paczki – dostawcy limitują liczbę tokenów w jednym zapytaniu
            odp = self._post("/embeddings", {"model": self.model_embed, "input": teksty[i : i + 16]})
            dane = sorted(odp.json()["data"], key=lambda d: d.get("index", 0))
            wektory.extend(d["embedding"] for d in dane)
        return wektory

    # ---------------------------------------------------------------- czat
    def czat_strumien(self, wiadomosci: list[dict], model: str | None = None) -> Iterator[str]:
        model = model or self.model_llm
        dane = {"model": model, "messages": wiadomosci, "temperature": self.temperatura,
                "max_tokens": self.maks_tokenow, "stream": True}
        # Zapytanie z ponowieniem przy 429 – sam strumień czytamy dopiero po udanym połączeniu.
        for proba in range(4):
            try:
                with self._http.stream("POST", f"{self.host}/chat/completions", json=dane) as odp:
                    if odp.status_code == 429 or odp.status_code >= 500:
                        odp.read()
                        if proba == 3:
                            raise self._blad(None, odp)
                        time.sleep(1.5 * (proba + 1))
                        continue
                    if odp.status_code >= 400:
                        odp.read()
                        raise self._blad(None, odp)
                    for linia in odp.iter_lines():
                        if not linia.startswith("data:"):
                            continue
                        tresc = linia[5:].strip()
                        if tresc == "[DONE]":
                            return
                        try:
                            kawalek = json.loads(tresc)
                        except ValueError:
                            continue
                        wybory = kawalek.get("choices") or []
                        tekst = (wybory[0].get("delta") or {}).get("content") if wybory else None
                        if tekst:
                            yield tekst
                    return
            except httpx.HTTPError as e:
                raise self._blad(e) from e

    def czat(self, wiadomosci: list[dict], model: str | None = None) -> str:
        return "".join(self.czat_strumien(wiadomosci, model))

    # ---------------------------------------------------------------- diagnostyka
    def dostepne_modele(self) -> list[str]:
        try:
            odp = self._http.get(f"{self.host}/models")
        except httpx.HTTPError as e:
            raise self._blad(e) from e
        if odp.status_code >= 400:
            raise self._blad(None, odp)
        return [m.get("id", "") for m in odp.json().get("data", [])]

    def sprawdz(self) -> list[str]:
        """Lista problemów (pusta = gotowe). Wynik pamiętamy 5 minut, bo strona woła to przy każdym kliknięciu."""
        if self._sprawdzone and time.time() - self._sprawdzone[0] < 300:
            return self._sprawdzone[1]
        problemy: list[str] = []
        if not self._klucz:
            problemy.append("Brak klucza API – ustaw API_KLUCZ w ustawieniach aplikacji (Secrets).")
        else:
            try:
                modele = self.dostepne_modele()
                if modele and not any(m == self.model_llm or m.endswith("/" + self.model_llm) for m in modele):
                    problemy.append(f"Dostawca nie udostępnia modelu '{self.model_llm}'. Dostępne m.in.: "
                                    + ", ".join(sorted(modele)[:8]))
            except BladOllamy as e:
                problemy.append(str(e))
        self._sprawdzone = (time.time(), problemy)
        return problemy
