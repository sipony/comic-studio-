"""Un registro di Ollama finto: tag delle famiglie, manifest con le dimensioni e la pagina dei tag del sito."""
from __future__ import annotations

import threading
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from finto_comfy import _porta_libera

GB = 1_000_000_000
# famiglia → tag → (byte, impronta del file del modello)
TAG = {
    "qwen3": {
        "latest": (5_225_000_000, "sha256:q8b4"), "8b": (5_225_000_000, "sha256:q8b4"),
        "8b-q4_K_M": (5_225_000_000, "sha256:q8b4"), "8b-q8_0": (8_890_000_000, "sha256:q8b8"),
        "8b-fp16": (16_390_000_000, "sha256:q8b16"), "14b": (9_276_000_000, "sha256:q14b4"),
        "14b-q4_K_M": (9_276_000_000, "sha256:q14b4"), "14b-q8_0": (15_700_000_000, "sha256:q14b8"),
        "32b-q4_K_M": (20_200_000_000, "sha256:q32b4"), "30b-a3b-q4_K_M": (18_560_000_000, "sha256:q30b4"),
        "235b-a22b-q4_K_M": (142_000_000_000, "sha256:q235"),
    },
    # solo dalla pagina del sito: il registro risponde 404 alla lista dei tag
    "gemma3": {"12b": (8_149_000_000, "sha256:g12"), "12b-it-q4_K_M": (8_149_000_000, "sha256:g12"),
               "12b-it-qat": (8_900_000_000, "sha256:g12qat"), "12b-pt-q4_K_M": (8_000_000_000, "sha256:g12pt"),
               "4b-it-q4_K_M": (3_338_000_000, "sha256:g4")},
    "nuovo-modello": {"7b": (4_700_000_000, "sha256:n7"), "7b-q4_K_M": (4_700_000_000, "sha256:n7"),
                      "7b-q6_K": (6_300_000_000, "sha256:n76"), "7b-cloud": (0, "sha256:x")},
}


class FintoRegistro:
    def __init__(self):
        self.richieste: list[str] = []
        self.porta = _porta_libera()
        self.url = f"http://127.0.0.1:{self.porta}"
        self.app = self._crea()
        self._server: uvicorn.Server | None = None

    def _crea(self) -> FastAPI:
        app = FastAPI()

        @app.middleware("http")
        async def registra(req: Request, chiama):
            self.richieste.append(req.url.path)
            return await chiama(req)

        @app.get("/v2/library/{fam}/tags/list")
        async def tags(fam: str):
            if fam not in TAG or fam == "gemma3":
                return JSONResponse({"errors": [{"code": "NAME_UNKNOWN"}]}, status_code=404)
            return {"name": f"library/{fam}", "tags": list(TAG[fam])}

        @app.get("/v2/library/{fam}/manifests/{tag}")
        async def manifest(fam: str, tag: str, req: Request):
            if tag not in TAG.get(fam, {}):
                return JSONResponse({"errors": []}, status_code=404)
            byte, impronta = TAG[fam][tag]
            return {"schemaVersion": 2, "config": {"size": 487},
                    "layers": [{"mediaType": "application/vnd.ollama.image.model", "digest": impronta, "size": byte},
                               {"mediaType": "application/vnd.ollama.image.template", "digest": "sha256:t",
                                "size": 1_000}]}

        @app.get("/library/{fam}/tags")
        async def pagina(fam: str):
            if fam not in TAG:
                return HTMLResponse("non trovato", status_code=404)
            righe = "".join(f'<a href="/library/{fam}:{t}"><span>{fam}:{t}</span></a>' for t in TAG[fam])
            return HTMLResponse(f"<html><body>{righe}</body></html>")

        return app

    def avvia(self):
        self._server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=self.porta, log_level="error"))
        threading.Thread(target=self._server.run, daemon=True).start()
        for _ in range(100):
            if self._server.started:
                return self
            time.sleep(0.05)
        raise RuntimeError("il finto registro non parte")

    def ferma(self):
        if self._server:
            self._server.should_exit = True
