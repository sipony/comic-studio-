"""Un Ollama finto per i test: /api/version, /api/tags, /api/pull (in streaming) e /api/chat con risposte fisse."""
from __future__ import annotations

import json
import threading
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from finto_comfy import _porta_libera

PERSONAGGIO = {
    "genere": "1girl", "adulto": True, "eta_apparente": "about 30",
    "tratti": ["long wavy auburn hair", "green eyes", "freckles", "scar on left cheek"],
    "abbigliamento": ["black leather jacket", "jeans"], "accessori": ["silver necklace"],
    "frase": "A woman in her thirties with long wavy auburn hair and green eyes.",
    "non_rappresentabile": ["è testarda e generosa"],
}

SCENA = {
    "soggetti": [
        {"personaggio": "mara", "descrizione": [], "posizione": "sinistra", "azione": ["holding axe", "running"],
         "posa": ["leaning forward"], "espressione": ["screaming"], "vestiti": ["torn clothes", "blood on clothes"],
         "adulto": True},
        {"personaggio": "", "descrizione": ["zombie", "rotting flesh"], "posizione": "destra",
         "azione": ["reaching out"], "posa": [], "espressione": [], "vestiti": [], "adulto": True},
    ],
    "interazione": ["fighting"], "inquadratura": ["wide shot", "from below"],
    "ambiente": ["abandoned hospital", "corridor"], "illuminazione": ["flickering light"],
    "atmosfera": ["horror"], "oggetti": ["broken window"], "effetti": ["blood splatter", "rain"],
    "elementi_chiave": ["axe", "zombie", "blood splatter", "corridor"], "negativo": ["sunlight"],
    "frase": "A woman with an axe fights a zombie in a dark hospital corridor.",
    "sessuale": False, "non_rappresentabile": ["l'odore di marcio"],
}

STORIA = {"pagine": [{"vignette": [
    {"formato": "larga", "personaggi": ["Mara"], "descrizione": "Mara entra nell'ospedale abbandonato.",
     "dialoghi": [{"chi": "narratore", "testo": "Era notte."}]},
    {"formato": "quadrata", "personaggi": ["mara", "sconosciuto"], "descrizione": "Primo piano di Mara spaventata.",
     "dialoghi": [{"chi": "mara", "testo": "C'è qualcuno?"}, {"chi": "", "testo": ""}]},
]}]}


class FintoOllama:
    def __init__(self, modelli: list[str] | None = None):
        self.modelli = list(modelli if modelli is not None else ["qwen3:8b"])
        self.richieste: list[dict] = []
        self.scena = SCENA
        self.app = self._crea()
        self.porta = _porta_libera()
        self.url = f"http://127.0.0.1:{self.porta}"
        self._server: uvicorn.Server | None = None

    def _crea(self) -> FastAPI:
        app = FastAPI()

        @app.get("/api/version")
        async def versione():
            return {"version": "0.40.11"}

        @app.get("/api/tags")
        async def tags():
            return {"models": [{"name": m} for m in self.modelli]}

        @app.post("/api/pull")
        async def pull(req: Request):
            corpo = await req.json()

            def righe():
                yield json.dumps({"status": "pulling manifest"}) + "\n"
                for fatto in (0, 50, 100):
                    yield json.dumps({"status": "downloading", "total": 100, "completed": fatto}) + "\n"
                self.modelli.append(corpo["model"])
                yield json.dumps({"status": "success"}) + "\n"
            return StreamingResponse(righe(), media_type="application/x-ndjson")

        @app.post("/api/chat")
        async def chat(req: Request):
            corpo = await req.json()
            self.richieste.append(corpo)
            if corpo["model"] not in self.modelli:
                return JSONResponse({"error": f"model '{corpo['model']}' not found"}, status_code=404)
            sistema = corpo["messages"][0]["content"]
            if "character description" in sistema:
                r = PERSONAGGIO
            elif "split a story" in sistema:
                r = STORIA
            else:
                r = self.scena
            return {"message": {"role": "assistant", "content": json.dumps(r)}, "done": True}

        return app

    def avvia(self):
        self._server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=self.porta, log_level="error"))
        threading.Thread(target=self._server.run, daemon=True).start()
        for _ in range(100):
            if self._server.started:
                return self
            time.sleep(0.05)
        raise RuntimeError("il finto Ollama non parte")

    def ferma(self):
        if self._server:
            self._server.should_exit = True
