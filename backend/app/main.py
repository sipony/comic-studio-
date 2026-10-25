"""Server di Comic Studio: API REST, WebSocket degli eventi e interfaccia Angular compilata."""
from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import __version__
from .comfy.client import ComfyErrore
from .rotte_dataset import rotte as rotte_dataset, rotte_comfy
from .projects import ErroreProgetto, ModificaPersonaggio, NuovoPersonaggio, suggerisci_trigger
from .settings import Archivio as ArchivioImpostazioni
from .state import App

RADICE = Path(__file__).resolve().parents[2]
INTERFACCIA = RADICE / "frontend" / "dist" / "comic-studio" / "browser"


class Usa(BaseModel):
    url: str | None = None
    cartella: str | None = None


class DatiProgetto(BaseModel):
    nome: str
    descrizione: str = ""


class ModificaProgetto(BaseModel):
    nome: str | None = None
    descrizione: str | None = None


def crea_app(app_stato: App | None = None, sorveglia: bool = True, host_consentiti: list[str] | None = None) -> FastAPI:
    stato = app_stato or App(ArchivioImpostazioni())

    @contextlib.asynccontextmanager
    async def ciclo(_: FastAPI):
        stato.bus.lega(asyncio.get_running_loop())
        stato.bus.log(f"Comic Studio {__version__} avviato", "info")
        compiti = []
        if sorveglia:
            compiti.append(asyncio.create_task(stato.sorveglia()))
            compiti.append(asyncio.create_task(stato.avvio()))
        yield
        for c in compiti:
            c.cancel()

    api = FastAPI(title="Comic Studio", version=__version__, lifespan=ciclo)
    api.state.app = stato
    # solo richieste indirizzate a questo computer (protegge dal DNS rebinding di pagine web malevole)
    api.add_middleware(TrustedHostMiddleware,
                       allowed_hosts=host_consentiti or ["127.0.0.1", "localhost", "[::1]", "testserver"])

    @api.exception_handler(ErroreProgetto)
    async def _errore_progetto(_: Request, e: ErroreProgetto):
        return JSONResponse({"detail": str(e)}, status_code=e.codice)

    @api.exception_handler(ComfyErrore)
    async def _errore_comfy(_: Request, e: ComfyErrore):
        return JSONResponse({"detail": str(e)}, status_code=502)

    # ------------------------------------------------------------ sistema e ComfyUI

    @api.get("/api/sistema")
    async def sistema():
        return {"versione": __version__, "impostazioni": stato.impostazioni.valori.model_dump(),
                "comfy": stato.comfy.dict(), "installazioni": [i.dict() for i in stato.installazioni],
                "ricerca_in_corso": stato.ricerca_in_corso, "rapporto": stato.rapporto}

    @api.post("/api/comfy/cerca")
    async def cerca_comfy():
        return stato.avvia_ricerca(auto_seleziona=True).dict()

    @api.post("/api/comfy/usa")
    async def usa_comfy(dati: Usa):
        try:
            stato.usa(dati.url, dati.cartella)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        stato.bus.log(f"Impostazioni di ComfyUI aggiornate: {dati.url or '-'} · {dati.cartella or '-'}")
        return (await stato.aggiorna_comfy()).dict()

    @api.get("/api/comfy/stato")
    async def stato_comfy():
        return (await stato.aggiorna_comfy()).dict()

    @api.get("/api/diagnostica")
    async def rapporto():
        return stato.rapporto

    @api.post("/api/diagnostica")
    async def nuova_diagnostica(rete: bool = True):
        return stato.avvia_diagnostica(rete).dict()

    @api.get("/api/comfy/modelli")
    async def modelli():
        return await stato.modelli()

    # ------------------------------------------------------------ progetti

    @api.get("/api/progetti")
    async def progetti():
        return [p.model_dump() for p in stato.progetti.elenco()]

    @api.post("/api/progetti", status_code=201)
    async def crea_progetto(dati: DatiProgetto):
        if not dati.nome.strip():
            raise HTTPException(400, "Il nome del progetto è obbligatorio")
        p = stato.progetti.crea(dati.nome, dati.descrizione)
        stato.impostazioni.aggiorna(ultimo_progetto=p.id)
        stato.bus.log(f"Creato il progetto «{p.nome}»", "ok")
        return p.model_dump()

    @api.get("/api/progetti/{pid}")
    async def leggi_progetto(pid: str):
        p = stato.progetti.leggi(pid)
        if stato.impostazioni.valori.ultimo_progetto != pid:
            stato.impostazioni.aggiorna(ultimo_progetto=pid)
        return p.model_dump()

    @api.patch("/api/progetti/{pid}")
    async def modifica_progetto(pid: str, dati: ModificaProgetto):
        return stato.progetti.modifica(pid, dati.nome, dati.descrizione).model_dump()

    @api.delete("/api/progetti/{pid}", status_code=204)
    async def elimina_progetto(pid: str):
        nome = stato.progetti.leggi(pid).nome
        stato.progetti.elimina(pid)
        if stato.impostazioni.valori.ultimo_progetto == pid:
            stato.impostazioni.aggiorna(ultimo_progetto=None)
        stato.bus.log(f"Progetto «{nome}» spostato nel cestino", "avviso")

    # ------------------------------------------------------------ personaggi

    @api.get("/api/trigger/suggerisci")
    async def suggerisci(nome: str, progetto: str | None = None):
        esistenti = {c.trigger for c in stato.progetti.leggi(progetto).personaggi} if progetto else set()
        return {"trigger": suggerisci_trigger(nome, esistenti)}

    @api.post("/api/progetti/{pid}/personaggi", status_code=201)
    async def aggiungi_personaggio(pid: str, dati: NuovoPersonaggio):
        c = stato.progetti.aggiungi_personaggio(pid, dati)
        stato.bus.log(f"Aggiunto il personaggio {c.nome} (trigger «{c.trigger}»)", "ok")
        return c.model_dump()

    @api.patch("/api/progetti/{pid}/personaggi/{cid}")
    async def modifica_personaggio(pid: str, cid: str, dati: ModificaPersonaggio):
        return stato.progetti.modifica_personaggio(pid, cid, dati).model_dump()

    @api.delete("/api/progetti/{pid}/personaggi/{cid}", status_code=204)
    async def elimina_personaggio(pid: str, cid: str):
        stato.progetti.elimina_personaggio(pid, cid)

    @api.put("/api/progetti/{pid}/personaggi/{cid}/riferimento")
    async def carica_riferimento(pid: str, cid: str, file: UploadFile = File(...)):
        dati = await file.read()
        c = stato.progetti.salva_riferimento(pid, cid, dati)
        stato.bus.log(f"Immagine di riferimento di {c.nome} aggiornata", "ok")
        return c.model_dump()

    @api.get("/api/progetti/{pid}/personaggi/{cid}/riferimento")
    async def riferimento(pid: str, cid: str):
        return FileResponse(stato.progetti.file_riferimento(pid, cid), headers={"Cache-Control": "no-cache"})

    # ------------------------------------------------------------ lavori e log

    @api.get("/api/lavori")
    async def lavori():
        return [l.dict() for l in sorted(stato.gestore.lavori.values(), key=lambda x: -x.creato)]

    @api.post("/api/lavori/{lid}/annulla")
    async def annulla(lid: str):
        if not stato.gestore.annulla(lid):
            raise HTTPException(404, "Lavoro non trovato o già concluso")
        return {"ok": True}

    @api.get("/api/log")
    async def log(n: int = 500):
        return list(stato.bus.storico)[-max(1, min(n, 2000)):]

    @api.websocket("/api/eventi")
    async def eventi(ws: WebSocket):
        await ws.accept()
        q = stato.bus.iscrivi()
        try:
            await ws.send_json({"tipo": "benvenuto", "comfy": stato.comfy.dict(),
                                "lavori": [l.dict() for l in stato.gestore.attivi()]})
            while True:
                await ws.send_json(await q.get())
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            stato.bus.disiscrivi(q)

    api.include_router(rotte_dataset)
    api.include_router(rotte_comfy)

    @api.get("/api/{resto:path}")
    async def api_sconosciuta(resto: str):
        raise HTTPException(404, f"Endpoint /api/{resto} inesistente")

    # ------------------------------------------------------------ interfaccia

    if INTERFACCIA.is_dir():
        @api.get("/{percorso:path}", include_in_schema=False)
        async def interfaccia(percorso: str):
            f = (INTERFACCIA / percorso).resolve()
            if percorso and f.is_file() and INTERFACCIA in f.parents:
                return FileResponse(f)
            return FileResponse(INTERFACCIA / "index.html", headers={"Cache-Control": "no-cache"})
    else:
        @api.get("/", include_in_schema=False)
        async def senza_interfaccia():
            return JSONResponse({"detail": "Interfaccia non compilata: esegui l'avvio con avvia.bat / avvia.sh, "
                                           "oppure 'npm run build' nella cartella frontend."}, status_code=503)

    return api
