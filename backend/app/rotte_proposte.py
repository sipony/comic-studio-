"""API del personaggio dal nulla: proposte d'immagine di riferimento generate dal testo."""
from __future__ import annotations

import asyncio
import random

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from . import testo_prompt as tp
from .comfy.client import ComfyErrore
from .jobs import Lavoro
from .modelinfo import TAG_QUALITA, famiglia_da_nome
from .projects import ErroreProgetto, ModificaPersonaggio
from .proposte import ArchivioProposte, ConfigProposte, prompt_proposta, workflow
from .workflows import per_invio

rotte = APIRouter(prefix="/api/progetti/{pid}/personaggi/{cid}/proposte")


def _app(req: Request):
    return req.app.state.app


def _personaggio(app, pid: str, cid: str):
    p = next((c for c in app.progetti.leggi(pid).personaggi if c.id == cid), None)
    if p is None:
        raise ErroreProgetto("Personaggio inesistente", 404)
    return p


@rotte.get("")
async def elenco(pid: str, cid: str, req: Request):
    app = _app(req)
    _personaggio(app, pid, cid)
    return [x.model_dump() for x in ArchivioProposte(app.progetti).elenco(pid, cid)]


@rotte.post("")
async def genera(pid: str, cid: str, c: ConfigProposte, req: Request):
    app = _app(req)
    p = _personaggio(app, pid, cid)
    if not app.comfy.connesso:
        raise ErroreProgetto("ComfyUI non è connesso: avvialo e riprova.", 409)
    if not p.descrizione.strip() and not p.storia.strip():
        raise ErroreProgetto(f"Scrivi prima la descrizione di {p.nome}.")
    tp.verifica_contenuto([p.storia, p.descrizione, c.extra, c.stile], minori=p.adulto is False)
    archivio = ArchivioProposte(app.progetti)
    origine = archivio.file(pid, cid, c.da) if c.da else None
    qualita = TAG_QUALITA.get(famiglia_da_nome(c.checkpoint) or "sdxl", TAG_QUALITA["sdxl"])

    async def lavoro(l: Lavoro):
        nonlocal p
        if not p.descrizione.strip():
            from .rotte_testo import tratti_dal_testo
            l.avanza(0.02, f"l'IA legge la descrizione di {p.nome}")
            r = await tratti_dal_testo(app, p, p.storia, c.checkpoint, l)
            p = app.progetti.modifica_personaggio(pid, cid, ModificaPersonaggio(
                descrizione=r["descrizione"], genere=r["genere"], adulto=r["adulto"]))
            app.bus.pubblica({"tipo": "personaggi", "progetto": pid, "personaggio": cid})
        positivo, negativo = prompt_proposta(p, c, qualita)
        l.log(f"Prompt di {p.nome}: {positivo}")
        async with app.client() as client:
            nome_origine = await client.carica_immagine(origine, "comic_studio_proposte") if origine else None
            for i in range(c.numero):
                l.controlla()
                seme = random.randrange(2 ** 48)
                wf, salva = workflow(c, positivo, negativo, seme, nome_origine)

                def avanza(x, t, i=i):
                    l.avanza(0.05 + 0.95 * (i + x) / c.numero, f"proposta {i + 1}/{c.numero} · {t}")
                try:
                    uscite = await client.esegui(per_invio(wf), avanza)
                except asyncio.CancelledError:
                    await client.interrompi()
                    raise
                img = (uscite.get(salva) or next(iter(uscite.values()), [None]))[0]
                if not img:
                    raise ComfyErrore("ComfyUI non ha restituito l'immagine.")
                dati = await client.scarica(img)
                await asyncio.to_thread(archivio.aggiungi, pid, cid, dati, seme, positivo, c.da)
                app.bus.pubblica({"tipo": "proposte", "progetto": pid, "personaggio": cid})
        l.log(f"{c.numero} proposte per {p.nome}: scegli quella giusta come immagine di riferimento", "ok")
        return {"generate": c.numero}

    titolo = f"{'Varianti' if c.da else 'Proposte'} per {p.nome}"
    return app.gestore.avvia("proposte", titolo, lavoro, progetto=pid, esclusivo=True).dict()


@rotte.get("/{nome}")
async def immagine(pid: str, cid: str, nome: str, req: Request):
    return FileResponse(ArchivioProposte(_app(req).progetti).file(pid, cid, nome),
                        headers={"Cache-Control": "max-age=86400"})


@rotte.post("/{nome}/scegli")
async def scegli(pid: str, cid: str, nome: str, req: Request):
    app = _app(req)
    a = ArchivioProposte(app.progetti)
    dati = await asyncio.to_thread(a.file(pid, cid, nome).read_bytes)
    c = app.progetti.salva_riferimento(pid, cid, dati)
    a.segna_scelta(pid, cid, nome)
    app.bus.log(f"Immagine di riferimento di {c.nome}: {nome}", "ok")
    return c.model_dump()


@rotte.post("/scarta")
async def scarta(pid: str, cid: str, req: Request):
    n = ArchivioProposte(_app(req).progetti).scarta(pid, cid)
    return {"spostate_nel_cestino": n}
