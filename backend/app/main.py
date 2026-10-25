"""Server di Comic Studio: API REST, WebSocket degli eventi e interfaccia Angular compilata."""
from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from . import __version__
from .comfy.client import ComfyErrore
from .llm import ErroreIA
from .rotte_dataset import rotte as rotte_dataset, rotte_comfy
from .rotte_didascalie import rotte as rotte_didascalie
from .rotte_addestramento import rotte as rotte_addestramento, rotte_kohya
from .rotte_fumetto import rotte as rotte_fumetto
from .rotte_testo import rotte as rotte_testo, rotte_ia
from .rotte_proposte import rotte as rotte_proposte
from .projects import ErroreProgetto, ModificaPersonaggio, NuovoPersonaggio, suggerisci_trigger
from .settings import Archivio as ArchivioImpostazioni
from .state import App

RADICE = Path(__file__).resolve().parents[2]
INTERFACCIA = RADICE / "frontend" / "dist" / "comic-studio" / "browser"


class Usa(BaseModel):
    url: str | None = None
    cartella: str | None = None


class AvvioComfy(BaseModel):
    avvio_automatico: bool | None = None
    argomenti_comfy: str | None = None
    comando_comfy: str | None = None
    attesa_avvio: int | None = None


class Esci(BaseModel):
    comfy: bool = False          # chiudi anche il ComfyUI avviato da Comic Studio


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
            compiti.append(asyncio.create_task(stato.avvio()))      # prima: segna che si sta preparando
            compiti.append(asyncio.create_task(stato.sorveglia()))
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

    @api.exception_handler(ErroreIA)
    async def _errore_ia(_: Request, e: ErroreIA):
        return JSONResponse({"detail": str(e), "codice": e.codice}, status_code=503)

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

    @api.post("/api/esci")
    async def esci(dati: Esci, request: Request):
        spegni = getattr(request.app.state, "spegni", None)
        if spegni is None:
            raise HTTPException(409, "Questo Comic Studio non si può chiudere dall'interfaccia.")
        lavori = [l for l in stato.gestore.attivi() if l.tipo not in ("diagnostica", "ricerca_comfy")]
        for l in lavori:
            stato.gestore.annulla(l.id)
        if dati.comfy and stato.comfy_pid:
            from .comfy import avvio as avvio_comfy
            pid, stato.comfy_pid = stato.comfy_pid, None
            await asyncio.to_thread(avvio_comfy.ferma, pid)
            stato.file_pid_comfy.unlink(missing_ok=True)
            stato.bus.log("ComfyUI chiuso", "ok")
        await stato.ia.ferma_ollama()          # solo se l'ha avviato Comic Studio
        stato.bus.log("Comic Studio si chiude", "info")
        stato.bus.pubblica({"tipo": "chiusura"})
        asyncio.get_running_loop().call_later(0.5, spegni)
        return {"ok": True, "annullati": len(lavori)}

    @api.post("/api/comfy/avvia")
    async def avvia_comfy():
        return stato.avvia_comfy().dict()

    @api.post("/api/comfy/ferma")
    async def ferma_comfy():
        if not stato.comfy_pid:
            raise HTTPException(409, "Posso fermare solo un ComfyUI avviato da Comic Studio: "
                                     "questo l'hai aperto tu, chiudilo dalla sua finestra.")
        return stato.ferma_comfy().dict()

    @api.post("/api/comfy/riavvia")
    async def riavvia_comfy():
        if stato.comfy.connesso and not stato.comfy_pid:
            raise HTTPException(409, "ComfyUI non è stato avviato da Comic Studio: chiudilo tu e poi premi Avvia.")
        return stato.riavvia_comfy().dict()

    @api.post("/api/comfy/avvio")
    async def impostazioni_avvio(dati: AvvioComfy):
        campi = dati.model_dump(exclude_none=True)
        if "comando_comfy" in campi:
            campi["comando_comfy"] = campi["comando_comfy"].strip() or None
        if "attesa_avvio" in campi:
            campi["attesa_avvio"] = max(30, min(campi["attesa_avvio"], 1800))
        stato.impostazioni.aggiorna(**campi)
        return (await stato.aggiorna_comfy()).dict() | {"impostazioni": stato.impostazioni.valori.model_dump()}

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

    @api.get("/api/lavori/{lid}")
    async def lavoro(lid: str):
        l = stato.gestore.lavori.get(lid)
        if not l:
            raise HTTPException(404, "Lavoro inesistente")
        return l.dict() | {"risultato": l.risultato if l.stato == "completato" else None}

    @api.get("/api/lavori/{lid}/anteprima")
    async def anteprima_lavoro(lid: str):
        l = stato.gestore.lavori.get(lid)
        if not l or not l.anteprima:
            raise HTTPException(404, "Nessuna anteprima")
        dati, tipo = l.anteprima
        return Response(dati, media_type=tipo, headers={"Cache-Control": "no-store"})

    @api.post("/api/lavori/annulla")
    async def annulla_tutti():
        return {"annullati": stato.gestore.annulla_tutti()}

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
    api.include_router(rotte_didascalie)
    api.include_router(rotte_addestramento)
    api.include_router(rotte_kohya)
    api.include_router(rotte_fumetto)
    api.include_router(rotte_comfy)
    api.include_router(rotte_ia)
    api.include_router(rotte_testo)
    api.include_router(rotte_proposte)

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
