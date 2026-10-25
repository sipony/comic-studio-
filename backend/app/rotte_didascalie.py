"""API e lavori dello Step 2 (Didascalie)."""
from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from .dataset import ArchivioDataset
from .didascalie import ArchivioDidascalie, ConfigDidascalie, carica_tagger
from .jobs import Lavoro
from .projects import slug
from .settings import cartella_dati

rotte = APIRouter(prefix="/api/progetti/{pid}/personaggi/{cid}/didascalie")


def _app(req: Request):
    return req.app.state.app


def _archivio(req: Request) -> ArchivioDidascalie:
    return ArchivioDidascalie(ArchivioDataset(_app(req).progetti))


def _avvisa(req: Request, pid: str, cid: str):
    _app(req).bus.pubblica({"tipo": "didascalie", "progetto": pid, "personaggio": cid})


@rotte.get("")
async def stato(pid: str, cid: str, req: Request):
    return await asyncio.to_thread(_archivio(req).stato, pid, cid)


@rotte.put("/config")
async def salva_config(pid: str, cid: str, c: ConfigDidascalie, req: Request):
    a = _archivio(req)
    await asyncio.to_thread(a.salva_config, pid, cid, c)
    return await asyncio.to_thread(a.stato, pid, cid)


class Testo(BaseModel):
    testo: str


@rotte.put("/immagini/{file}")
async def scrivi(pid: str, cid: str, file: str, dati: Testo, req: Request):
    a = _archivio(req)
    if file not in {i.file for i in a.immagini(pid, cid)[0]}:
        raise HTTPException(404, "Immagine non presente nel dataset")
    a.imposta_manuale(pid, cid, file, dati.testo)
    return {"ok": True}


@rotte.delete("/immagini/{file}")
async def ripristina(pid: str, cid: str, file: str, req: Request):
    _archivio(req).imposta_manuale(pid, cid, file, None)
    return {"ok": True}


class Analizza(BaseModel):
    tutte: bool = False      # rianalizza anche le immagini già fatte


@rotte.post("/analizza")
async def analizza(pid: str, cid: str, dati: Analizza, req: Request):
    app = _app(req)
    a = _archivio(req)
    _, pers = a.dataset.personaggio(pid, cid)
    imm, _ = a.immagini(pid, cid)
    if not imm:
        raise HTTPException(400, "Non ci sono immagini nel dataset: completa prima lo Step 1.")
    c = a.config(pid, cid)
    fatte = a.tag(pid, cid)
    da_fare = [i for i in imm if dati.tutte or i.file not in fatte]

    async def lavoro(l: Lavoro):
        if not da_fare:
            l.log("Tutte le immagini sono già state analizzate.", "ok")
            return {"analizzate": 0}
        l.avanza(0.01, "preparo il tagger")
        tagger = await asyncio.to_thread(carica_tagger, cartella_dati() / "modelli", c.modello,
                                         lambda v, t: l.avanza(v * 0.4, t), l.log)
        cartella = a.dataset.cartella(pid, cid) / "generate"
        inizio = time.time()
        risultati = await asyncio.to_thread(tagger.tagga, [cartella / i.file for i in da_fare],
                                            lambda v, t: l.avanza(0.4 + v * 0.6, t), lambda: l.annullato)
        a.salva_tag(pid, cid, risultati)
        l.controlla()
        _avvisa(req, pid, cid)
        l.log(f"Analizzate {len(risultati)} immagini di {pers.nome} in {time.time() - inizio:.0f} s", "ok")
        return {"analizzate": len(risultati)}

    return app.gestore.avvia("didascalie_analizza", f"Tag automatici di {pers.nome}", lavoro, progetto=pid).dict()


@rotte.get("/zip")
async def scarica_zip(pid: str, cid: str, req: Request):
    a = _archivio(req)
    _, pers = a.dataset.personaggio(pid, cid)
    dati = await asyncio.to_thread(a.zip, pid, cid)
    nome = f"dataset_{slug(pers.nome)}_{pers.trigger}.zip"
    return Response(dati, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{nome}"'})
