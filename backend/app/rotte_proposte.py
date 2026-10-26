"""API del personaggio dal nulla: proposte d'immagine di riferimento generate dal testo."""
from __future__ import annotations

import asyncio
import random

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse
from . import testo_prompt as tp
from .comfy.client import ComfyErrore
from .jobs import Lavoro
from .modelinfo import TAG_QUALITA, famiglia_da_nome
from .projects import ErroreProgetto, ModificaPersonaggio
from .proposte import ArchivioProposte, ConfigProposte, prompt_proposta, ricetta_da, workflow
from .dataset import ArchivioDataset
from .rotte_dataset import prepara_come_proposte
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
        ricetta = ricetta_da(c)
        l.log(f"Prompt di {p.nome}: {positivo}")
        if c.lora_stile:
            l.log(f"LoRA di stile: {c.lora_stile} (forza {c.forza_lora})")
        async with app.client() as client:
            nome_origine = await client.carica_immagine(origine, "comic_studio_proposte") if origine else None
            for i in range(c.numero):
                l.controlla()
                seme = random.randrange(2 ** 48)
                wf, salva = workflow(c, positivo, negativo, seme, nome_origine)

                def avanza(x, t, i=i):
                    l.avanza(0.05 + 0.95 * (i + x) / c.numero, f"proposta {i + 1}/{c.numero} · {t}")
                l.registra_workflow(wf, {"tipo": "proposte", "progetto": pid, "personaggio": cid,
                                         "variante": bool(c.da)})
                uscite = await client.esegui(per_invio(wf), avanza, anteprima=l.imposta_anteprima)
                img = (uscite.get(salva) or next(iter(uscite.values()), [None]))[0]
                if not img:
                    raise ComfyErrore("ComfyUI non ha restituito l'immagine.")
                dati = await client.scarica(img)
                l.imposta_anteprima(dati, "image/png", finale=True)
                await asyncio.to_thread(archivio.aggiungi, pid, cid, dati, seme, positivo, c.da, ricetta, wf)
                app.bus.pubblica({"tipo": "proposte", "progetto": pid, "personaggio": cid})
        l.log(f"{c.numero} proposte per {p.nome}: scegli quella giusta come immagine di riferimento", "ok")
        return {"generate": c.numero}

    titolo = f"{'Varianti' if c.da else 'Proposte'} per {p.nome}"
    return app.gestore.avvia("proposte", titolo, lavoro, progetto=pid, esclusivo=True).dict()


@rotte.post("/anteprima")
async def anteprima(pid: str, cid: str, c: ConfigProposte, req: Request):
    """Il prompt positivo e negativo che userebbero le proposte, senza generare niente."""
    p = _personaggio(_app(req), pid, cid)
    famiglia = famiglia_da_nome(c.checkpoint) or "sdxl"
    if not p.descrizione.strip():
        return {"positivo": None, "negativo": None, "famiglia": famiglia,
                "nota": "I tratti li ricava l'IA dalla descrizione libera quando generi."}
    positivo, negativo = prompt_proposta(p, c, TAG_QUALITA.get(famiglia, TAG_QUALITA["sdxl"]))
    return {"positivo": positivo, "negativo": negativo, "famiglia": famiglia, "nota": None}


@rotte.get("/{nome}")
async def immagine(pid: str, cid: str, nome: str, req: Request):
    return FileResponse(ArchivioProposte(_app(req).progetti).file(pid, cid, nome),
                        headers={"Cache-Control": "max-age=86400"})


@rotte.get("/{nome}/workflow")
async def workflow_proposta(pid: str, cid: str, nome: str, req: Request, formato: str = "grafo"):
    """Il workflow con cui è stata fatta la proposta (salvato, o ricostruito per quelle vecchie)."""
    from .rotte_dataset import _json_scaricabile, pacchetto_grafo
    app = _app(req)
    pers = _personaggio(app, pid, cid)
    wf, ricostruito = ArchivioProposte(app.progetti).workflow_di(pid, cid, nome)
    if formato == "json":
        return _json_scaricabile(wf, f"comic-studio-{cid}-{nome.removesuffix('.png')}.json")
    return await pacchetto_grafo(app, wf, f"Proposta di {pers.nome} · {nome}", ricostruito, "proposta",
                                 f"/api/progetti/{pid}/personaggi/{cid}/proposte/{nome}/workflow?formato=json")


@rotte.post("/{nome}/scegli")
async def scegli(pid: str, cid: str, nome: str, req: Request):
    app = _app(req)
    a = ArchivioProposte(app.progetti)
    dati = await asyncio.to_thread(a.file(pid, cid, nome).read_bytes)
    proposta = a.leggi(pid, cid, nome)
    origine = proposta.ricetta.model_dump() if proposta and proposta.ricetta else None
    c = app.progetti.salva_riferimento(pid, cid, dati, origine)
    a.segna_scelta(pid, cid, nome)
    app.bus.log(f"Immagine di riferimento di {c.nome}: {nome}", "ok")
    # il dataset riparte dalle stesse scelte, se non ha già un workflow scelto dall'utente
    if origine and not ArchivioDataset(app.progetti).config(pid, cid).workflow:
        try:
            await prepara_come_proposte(app, pid, cid, origine)
        except Exception as e:  # noqa: BLE001 - il riferimento è salvato comunque
            app.bus.log(f"Non sono riuscito a preparare il dataset come le proposte: {e}", "avviso")
    return c.model_dump()


class RicettaVecchia(BaseModel):
    checkpoint: str = Field(min_length=1)


@rotte.post("/{nome}/ricetta")
async def ricetta_vecchia(pid: str, cid: str, nome: str, dati: RicettaVecchia, req: Request):
    """Completa una proposta fatta prima della 0.16 (senza ricetta) con il checkpoint usato: stile e inquadratura si
    leggono dal suo prompt, campionamento e negativo erano fissi. Se è il riferimento, il personaggio la ricorda."""
    from .coerenza import ricetta_da_proposta_vecchia
    from .proposte import Ricetta
    app = _app(req)
    pers = _personaggio(app, pid, cid)
    a = ArchivioProposte(app.progetti)
    p = a.leggi(pid, cid, nome)
    if p is None:
        raise ErroreProgetto("Proposta inesistente", 404)
    if p.ricetta:
        raise ErroreProgetto("Questa proposta ricorda già come è stata fatta.", 409)
    try:
        r = ricetta_da_proposta_vecchia(p, pers, dati.checkpoint)
    except ValueError as e:
        raise ErroreProgetto(str(e)) from None
    a.imposta_ricetta(pid, cid, nome, Ricetta(**r))
    if p.scelta:
        app.progetti.modifica_personaggio(pid, cid, ModificaPersonaggio(origine=r))
        app.bus.pubblica({"tipo": "personaggi", "progetto": pid, "personaggio": cid})
    app.bus.log(f"Proposta {nome} di {pers.nome}: ricetta ricostruita con {dati.checkpoint}", "ok")
    return r


@rotte.post("/scarta")
async def scarta(pid: str, cid: str, req: Request):
    n = ArchivioProposte(_app(req).progetti).scarta(pid, cid)
    return {"spostate_nel_cestino": n}
