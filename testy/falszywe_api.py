"""Atrapa API zgodnego z OpenAI (jak Mistral) do testów wersji w chmurze – bez klucza i bez internetu.

Udaje /v1/models, /v1/embeddings i /v1/chat/completions (ze strumieniowaniem SSE). Pierwsze zapytanie
o embeddingi celowo kończy się błędem 429 („za dużo zapytań”), żeby sprawdzić ponawianie.

Użycie:  python testy/falszywe_api.py 11600     (potem API_URL=http://127.0.0.1:11600/v1)
"""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from testy.falszywa_ollama import odpowiedz_modelu, osadz  # noqa: E402

STAN = {"embeddingi": 0}


class Obsluga(BaseHTTPRequestHandler):
    def log_message(self, *args):  # cisza w testach
        pass

    def _json(self, kod: int, dane: dict) -> None:
        tresc = json.dumps(dane).encode()
        self.send_response(kod)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(tresc)))
        self.end_headers()
        self.wfile.write(tresc)

    def _autoryzacja(self) -> bool:
        if self.headers.get("Authorization") != "Bearer klucz-testowy":
            self._json(401, {"message": "Unauthorized"})
            return False
        return True

    def do_GET(self):  # noqa: N802
        if not self._autoryzacja():
            return
        if self.path.endswith("/models"):
            self._json(200, {"data": [{"id": "mistral-small-latest"}, {"id": "mistral-embed"}]})
        else:
            self._json(404, {"message": "not found"})

    def do_POST(self):  # noqa: N802
        if not self._autoryzacja():
            return
        dane = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path.endswith("/embeddings"):
            STAN["embeddingi"] += 1
            if STAN["embeddingi"] == 1:
                self._json(429, {"message": "Requests rate limit exceeded"})
                return
            wejscie = dane["input"] if isinstance(dane["input"], list) else [dane["input"]]
            self._json(200, {"data": [{"index": i, "embedding": osadz(t)} for i, t in enumerate(wejscie)]})
        elif self.path.endswith("/chat/completions"):
            if "reasoning_effort" in dane:
                self._json(400, {"error": {"message": "Unknown name reasoning_effort"}})
                return
            if dane.get("model") == "model-przeciazony":
                self._json(503, {"error": {"code": 503, "message": "This model is currently experiencing high demand."}})
                return
            tekst = odpowiedz_modelu(dane["messages"])
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for slowo in tekst.split(" "):
                kawalek = {"choices": [{"index": 0, "delta": {"content": slowo + " "}}]}
                self.wfile.write(f"data: {json.dumps(kawalek)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            self._json(404, {"message": "not found"})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 11600
    ThreadingHTTPServer(("127.0.0.1", port), Obsluga).serve_forever()
