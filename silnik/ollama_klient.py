"""Cienka warstwa nad biblioteką `ollama`: embeddingi, czat (ze strumieniowaniem) i czytelne błędy."""
from __future__ import annotations

import time

from typing import Iterator, Sequence

import ollama


class BladOllamy(RuntimeError):
    """Błąd z podpowiedzią, co zrobić (wyświetlany użytkownikowi)."""


def _przetlumacz_blad(e: Exception, model: str, host: str) -> BladOllamy:
    tekst = str(e)
    if isinstance(e, ollama.ResponseError) and (e.status_code == 404 or "not found" in tekst.lower()):
        return BladOllamy(
            f"Ollama nie ma modelu '{model}'. Pobierz go: `ollama pull {model}` "
            f"(albo dla 'tenis-ekspert': `ollama create tenis-ekspert -f Modelfile`)."
        )
    if isinstance(e, (ConnectionError, OSError)) or "connect" in tekst.lower():
        return BladOllamy(
            f"Nie mogę połączyć się z Ollamą pod adresem {host}. "
            "Uruchom aplikację Ollama (albo w terminalu: `ollama serve`) i spróbuj ponownie."
        )
    return BladOllamy(f"Błąd Ollamy ({type(e).__name__}): {tekst}")


class KlientOllama:
    def __init__(self, host: str, model_llm: str, model_embed: str, temperatura: float = 0.2, num_ctx: int = 8192):
        self.host = host
        self.model_llm = model_llm
        self.model_embed = model_embed
        self.opcje = {"temperature": temperatura, "num_ctx": num_ctx}
        self._klient = ollama.Client(host=host)

    # ---------------------------------------------------------------- embeddingi
    def embed(self, teksty: Sequence[str], proby: int = 3) -> list[list[float]]:
        """Embeddingi z ponowieniem: na słabszym sprzęcie proces modelu w Ollamie potrafi się zrestartować
        w trakcie długiego liczenia (błąd „EOF”) – wtedy kolejna próba zwykle się udaje."""
        for proba in range(proby):
            try:
                odp = self._klient.embed(model=self.model_embed, input=list(teksty))
                return [list(w) for w in odp["embeddings"]]
            except Exception as e:  # noqa: BLE001
                trwaly = "not found" in str(e).lower() or isinstance(e, (ConnectionError, OSError))
                if trwaly or proba == proby - 1:
                    raise _przetlumacz_blad(e, self.model_embed, self.host) from e
                time.sleep(2 * (proba + 1))
        raise AssertionError("nieosiągalne")

    # ---------------------------------------------------------------- czat
    def czat_strumien(self, wiadomosci: list[dict], model: str | None = None) -> Iterator[str]:
        model = model or self.model_llm
        try:
            for kawalek in self._klient.chat(model=model, messages=wiadomosci, stream=True, options=self.opcje):
                tekst = kawalek["message"]["content"]
                if tekst:
                    yield tekst
        except Exception as e:  # noqa: BLE001
            raise _przetlumacz_blad(e, model, self.host) from e

    def czat(self, wiadomosci: list[dict], model: str | None = None) -> str:
        return "".join(self.czat_strumien(wiadomosci, model))

    # ---------------------------------------------------------------- diagnostyka
    def dostepne_modele(self) -> list[str]:
        try:
            odp = self._klient.list()
        except Exception as e:  # noqa: BLE001
            raise _przetlumacz_blad(e, "-", self.host) from e
        modele = odp.get("models", []) if isinstance(odp, dict) else getattr(odp, "models", [])
        nazwy = []
        for m in modele:
            nazwa = m.get("model") if isinstance(m, dict) else getattr(m, "model", None)
            nazwa = nazwa or (m.get("name") if isinstance(m, dict) else getattr(m, "name", None))
            if nazwa:
                nazwy.append(nazwa)
        return nazwy

    def sprawdz(self) -> list[str]:
        """Zwraca listę problemów (pusta lista = wszystko gotowe)."""
        try:
            modele = self.dostepne_modele()
        except BladOllamy as e:
            return [str(e)]

        def jest(nazwa: str) -> bool:
            baza = nazwa.split(":")[0].lower()
            return any(m.lower() == nazwa.lower() or m.lower().split(":")[0] == baza for m in modele)

        problemy = []
        if not jest(self.model_embed):
            problemy.append(f"Brak modelu embeddingów '{self.model_embed}' – uruchom: ollama pull {self.model_embed}")
        if not jest(self.model_llm):
            if self.model_llm == "tenis-ekspert":
                problemy.append("Brak modelu 'tenis-ekspert' – uruchom: ollama create tenis-ekspert -f Modelfile")
            else:
                problemy.append(f"Brak modelu '{self.model_llm}' – uruchom: ollama pull {self.model_llm}")
        return problemy
