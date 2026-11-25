"""Atrapa serwera Ollamy do testów automatycznych (bez pobierania modeli i bez GPU).

Udaje endpointy /api/tags, /api/embed i /api/chat. Embeddingi liczy "sztuczką haszującą"
(worek słów -> wektor), a "model językowy" odpowiada pierwszym fragmentem kontekstu.
Służy tylko do sprawdzenia, czy cały kod działa – NIE ocenia jakości prawdziwego modelu.

Użycie:  python testy/falszywa_ollama.py 11500     (potem OLLAMA_HOST=http://127.0.0.1:11500)
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from silnik.tekst import tokeny  # noqa: E402

WYMIAR = 256
MODELE = {"bge-m3:latest", "tenis-ekspert:latest"}


def osadz(tekst: str) -> list[float]:
    w = [0.0] * WYMIAR
    for t in tokeny(tekst):
        h = int(hashlib.md5(t.encode()).hexdigest(), 16)
        w[h % WYMIAR] += 1.0 if (h >> 8) % 2 else -1.0
    n = math.sqrt(sum(x * x for x in w)) or 1.0
    return [x / n for x in w]


def odpowiedz_modelu(wiadomosci: list[dict]) -> str:
    ostatnia = wiadomosci[-1]["content"]
    m = re.search(r"KONTEKST:\n\[(?:1|M)\][^\n]*\n(.+?)(?:\n\n\[\w+\]|\n\nPYTANIE:)", ostatnia, flags=re.S)
    if m:
        return "Na podstawie bazy wiedzy: " + " ".join(m.group(1).split())[:500] + " [1]"
    return "Nie mam pewności – odpowiadam bez bazy wiedzy."


class Obsluga(BaseHTTPRequestHandler):
    def log_message(self, *args):  # cisza w konsoli
        pass

    def _json(self, kod: int, dane: dict) -> None:
        tresc = json.dumps(dane).encode()
        self.send_response(kod)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(tresc)))
        self.end_headers()
        self.wfile.write(tresc)

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/api/tags"):
            self._json(200, {"models": [{"model": m, "name": m, "size": 1, "digest": "x"} for m in sorted(MODELE)]})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        dlugosc = int(self.headers.get("Content-Length", 0))
        dane = json.loads(self.rfile.read(dlugosc) or b"{}")
        model = dane.get("model", "")
        if model.split(":")[0] + ":latest" not in MODELE and model not in MODELE:
            self._json(404, {"error": f"model '{model}' not found"})
            return
        if self.path.startswith("/api/embed"):
            wejscie = dane["input"] if isinstance(dane["input"], list) else [dane["input"]]
            self._json(200, {"model": model, "embeddings": [osadz(t) for t in wejscie]})
        elif self.path.startswith("/api/chat"):
            tekst = odpowiedz_modelu(dane["messages"])
            if dane.get("stream", True):
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.end_headers()
                for slowo in re.findall(r"\S+\s*", tekst):
                    linia = {"model": model, "created_at": "2026-01-01T00:00:00Z",
                             "message": {"role": "assistant", "content": slowo}, "done": False}
                    self.wfile.write((json.dumps(linia) + "\n").encode())
                koniec = {"model": model, "created_at": "2026-01-01T00:00:00Z",
                          "message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop"}
                self.wfile.write((json.dumps(koniec) + "\n").encode())
            else:
                self._json(200, {"model": model, "created_at": "2026-01-01T00:00:00Z",
                                 "message": {"role": "assistant", "content": tekst}, "done": True})
        else:
            self._json(404, {"error": "not found"})


def uruchom(port: int) -> ThreadingHTTPServer:
    serwer = ThreadingHTTPServer(("127.0.0.1", port), Obsluga)
    return serwer


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 11500
    print(f"Atrapa Ollamy na http://127.0.0.1:{port}")
    uruchom(port).serve_forever()
