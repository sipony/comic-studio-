"""API dell'IA locale e del passaggio dal testo al prompt (personaggi, vignette, storia intera)."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import fumetto as fm
from . import testo_prompt as tp
from .jobs import Lavoro
from .llm import MODELLI_CONSIGLIATI, ErroreIA
from .modelinfo import famiglia_da_nome
from .projects import Personaggio

rotte_ia = APIRouter(prefix="/api/ia")
rotte = APIRouter(prefix="/api/progetti/{pid}")


def _app(req: Request):
    return req.app.state.app


# ---------------------------------------------------------------- IA locale

@rotte_ia.get("")
async def stato_ia(req: Request):
    s = await _app(req).ia.aggiorna()
    return s.dict() | {"consigliati": [{"nome": n, "descrizione": d, "gb": g} for n, d, g in MODELLI_CONSIGLIATI],
                       "impostazioni": _impostazioni(req)}


def _impostazioni(req: Request) -> dict:
    i = _app(req).impostazioni.valori
    return {"tipo": i.ia_tipo, "url": i.ia_url, "modello": i.ia_modello, "libera_gpu": i.ia_libera_gpu,
            "chiave_impostata": bool(i.ia_chiave)}


class ImpostazioniIA(BaseModel):
    tipo: str | None = Field(default=None, pattern="^(ollama|openai|nessuna)$")
    url: str | None = None
    modello: str | None = None
    chiave: str | None = None           # "" la cancella
    libera_gpu: bool | None = None


@rotte_ia.post("/impostazioni")
async def imposta_ia(dati: ImpostazioniIA, req: Request):
    campi = {}
    if dati.tipo is not None:
        campi["ia_tipo"] = dati.tipo
        if dati.url is None and dati.tipo == "ollama":
            campi["ia_url"] = "http://127.0.0.1:11434"
        if dati.url is None and dati.tipo == "openai":
            campi["ia_url"] = "http://127.0.0.1:1234"         # LM Studio
    if dati.url is not None:
        campi["ia_url"] = dati.url.strip().rstrip("/") or "http://127.0.0.1:11434"
    if dati.modello is not None and dati.modello.strip():
        campi["ia_modello"] = dati.modello.strip()
    if dati.chiave is not None:
        campi["ia_chiave"] = dati.chiave.strip() or None
    if dati.libera_gpu is not None:
        campi["ia_libera_gpu"] = dati.libera_gpu
    _app(req).impostazioni.aggiorna(**campi)
    return await stato_ia(req)


@rotte_ia.post("/installa")
async def installa_ia(req: Request):
    return _app(req).ia.installa().dict()


class Modello(BaseModel):
    nome: str = Field(min_length=1, max_length=120)


@rotte_ia.post("/modello")
async def scarica_modello(dati: Modello, req: Request):
    app = _app(req)
    app.impostazioni.aggiorna(ia_modello=dati.nome.strip())
    return app.ia.scarica_modello(dati.nome.strip()).dict()


class Prova(BaseModel):
    testo: str = Field(min_length=1, max_length=20000)
    checkpoint: str | None = None


@rotte_ia.post("/prova")
async def prova(dati: Prova, req: Request):
    """Analizza una scena di prova senza personaggi e mostra il prompt che ne verrebbe fuori."""
    app = _app(req)

    async def lavoro(l: Lavoro):
        l.avanza(0.1, "l'IA legge il testo")
        analisi = await app.ia.chiedi(tp.SISTEMA_SCENA, tp.richiesta_scena(dati.testo, [], []), tp.SCHEMA_SCENA, l)
        tp.verifica_scena(analisi, dati.testo, [])
        scena = tp.componi_scena(analisi, famiglia_da_nome(dati.checkpoint or ""), set())
        l.log(f"Prompt: {scena.globale}", "ok")
        return {"analisi": analisi, "prompt": scena.dict()}
    return app.gestore.avvia("ia_prova", "Prova dell'IA locale", lavoro).dict()


# ---------------------------------------------------------------- personaggi: descrizione lunga → tratti

class Tratti(BaseModel):
    storia: str | None = None           # se assente si usa quella salvata nel personaggio
    checkpoint: str | None = None


@rotte.post("/personaggi/{cid}/tratti")
async def ricava_tratti(pid: str, cid: str, dati: Tratti, req: Request):
    app = _app(req)
    progetto = app.progetti.leggi(pid)
    p = next((c for c in progetto.personaggi if c.id == cid), None)
    if p is None:
        raise HTTPException(404, "Personaggio inesistente")
    storia = (dati.storia if dati.storia is not None else p.storia).strip()
    if not storia:
        raise HTTPException(400, "Scrivi prima la descrizione del personaggio.")
    checkpoint = dati.checkpoint or fm.ArchivioFumetto(app.progetti).leggi(pid).impostazioni.checkpoint

    async def lavoro(l: Lavoro):
        l.avanza(0.1, f"l'IA legge la descrizione di {p.nome}")
        utente = f"Character name: {p.nome}\nDescription:\n{storia}"
        analisi = await app.ia.chiedi(tp.SISTEMA_PERSONAGGIO, utente, tp.SCHEMA_PERSONAGGIO, l)
        r = tp.tratti_personaggio(analisi, famiglia_da_nome(checkpoint or ""))
        tp.verifica_contenuto([storia, r["descrizione"]], minori=r["adulto"] is False)
        l.log(f"Tratti di {p.nome}: {r['descrizione']}", "ok")
        if r["adulto"] is False:
            l.log(f"{p.nome} risulta minorenne: nelle scene con lui o lei i contenuti sessuali sono bloccati.", "info")
        return r
    return app.gestore.avvia("ia_tratti", f"Tratti di {p.nome} dal testo", lavoro, progetto=pid).dict()


# ---------------------------------------------------------------- vignette: descrizione → prompt

async def analizza(app, pid: str, vid: str, l: Lavoro, forza: bool = False) -> tuple[dict, tp.PromptScena] | None:
    """Analisi della descrizione della vignetta (rifatta solo se il testo o i personaggi sono cambiati)."""
    a = fm.ArchivioFumetto(app.progetti)
    f = a.leggi(pid)
    v = a.trova(f, vid)
    if not v.descrizione.strip():
        return None
    personaggi: list[Personaggio] = app.progetti.leggi(pid).personaggi
    chiave = tp.chiave_analisi(v.descrizione, personaggi, v.personaggi, app.impostazioni.valori.ia_modello)
    if not forza and v.analisi and v.analisi.get("chiave") == chiave:
        dati = v.analisi["dati"]
    else:
        tp.verifica_contenuto([v.descrizione])          # prima ancora di chiedere all'IA
        dati = await app.ia.chiedi(tp.SISTEMA_SCENA, tp.richiesta_scena(v.descrizione, personaggi, v.personaggi),
                                   tp.SCHEMA_SCENA, l, contesto=16384)
        f = a.leggi(pid)                                 # nel frattempo l'utente può aver salvato
        v = a.trova(f, vid)
        v.analisi = {"chiave": chiave, "dati": dati}
        a.salva(pid, f)
    tp.verifica_scena(dati, v.descrizione, personaggi)
    scena = tp.componi_scena(dati, famiglia_da_nome(f.impostazioni.checkpoint or ""), {p.id for p in personaggi},
                             v.rafforza)
    if not v.personaggi and scena.personaggi:            # i personaggi li ha trovati l'IA nel testo
        f = a.leggi(pid)
        v = a.trova(f, vid)
        v.personaggi = scena.personaggi
        # l'analisi resta valida anche con i personaggi appena scelti
        v.analisi = {"chiave": tp.chiave_analisi(v.descrizione, personaggi, v.personaggi,
                                                 app.impostazioni.valori.ia_modello), "dati": dati}
        a.salva(pid, f)
    return dati, scena


@rotte.post("/fumetto/vignette/{vid}/analizza")
async def analizza_vignetta(pid: str, vid: str, req: Request, forza: bool = True):
    app = _app(req)
    fm.ArchivioFumetto(app.progetti).trova(fm.ArchivioFumetto(app.progetti).leggi(pid), vid)

    async def lavoro(l: Lavoro):
        l.avanza(0.1, "l'IA legge la descrizione")
        r = await analizza(app, pid, vid, l, forza=forza)
        if r is None:
            raise ErroreIA("La vignetta non ha una descrizione da analizzare.")
        dati, scena = r
        l.log(f"Scena: {scena.globale}", "ok")
        for pid_, t in scena.per_personaggio.items():
            l.log(f"  {pid_}: {t}", "info")
        if scena.non_rappresentabile:
            l.log("Non disegnabile: " + "; ".join(scena.non_rappresentabile), "debug")
        app.bus.pubblica({"tipo": "fumetto", "progetto": pid, "vignetta": vid})
        return {"analisi": dati, "prompt": scena.dict()}
    return app.gestore.avvia("fumetto_analisi", "Analisi della descrizione", lavoro, progetto=pid).dict()


@rotte.get("/fumetto/vignette/{vid}/prompt")
async def prompt_vignetta(pid: str, vid: str, req: Request):
    """Il prompt che verrà usato (senza chiamare l'IA): dall'ultima analisi salvata, se è ancora valida."""
    app = _app(req)
    a = fm.ArchivioFumetto(app.progetti)
    f = a.leggi(pid)
    v = a.trova(f, vid)
    personaggi = app.progetti.leggi(pid).personaggi
    if not v.descrizione.strip() or not v.analisi:
        return {"aggiornata": False, "prompt": None}
    chiave = tp.chiave_analisi(v.descrizione, personaggi, v.personaggi, app.impostazioni.valori.ia_modello)
    scena = tp.componi_scena(v.analisi["dati"], famiglia_da_nome(f.impostazioni.checkpoint or ""),
                             {p.id for p in personaggi}, v.rafforza)
    return {"aggiornata": v.analisi.get("chiave") == chiave, "prompt": scena.dict()}


# ---------------------------------------------------------------- storia intera → pagine e vignette

class Storia(BaseModel):
    testo: str = Field(min_length=1, max_length=200000)
    sostituisci: bool = False


@rotte.post("/fumetto/storia")
async def dividi_storia(pid: str, dati: Storia, req: Request):
    app = _app(req)
    personaggi = app.progetti.leggi(pid).personaggi
    pezzi = tp.spezza_storia(dati.testo)

    async def lavoro(l: Lavoro):
        pagine: list[dict] = []
        for i, pezzo in enumerate(pezzi):
            l.controlla()
            l.avanza(i / len(pezzi), f"l'IA divide la storia: parte {i + 1}/{len(pezzi)}")
            utente = f"{tp.elenco_personaggi(personaggi)}\n\nStory:\n{pezzo}"
            r = await app.ia.chiedi(tp.SISTEMA_STORIA, utente, tp.SCHEMA_STORIA, l, contesto=16384)
            nuove = tp.pagine_da_analisi(r, personaggi)
            l.log(f"Parte {i + 1}: {len(nuove)} pagine, {sum(len(p['vignette']) for p in nuove)} vignette", "info")
            pagine += nuove
        if not pagine:
            raise ErroreIA("L'IA non ha ricavato nessuna vignetta: prova con un modello più grande.")
        a = fm.ArchivioFumetto(app.progetti)
        f = a.leggi(pid)
        nuove = [fm.Pagina(vignette=[fm.Vignetta(**v) for v in p["vignette"]]) for p in pagine]
        vuoto = all(not p.vignette for p in f.pagine)
        f.pagine = nuove if (dati.sostituisci or vuoto) else f.pagine + nuove
        await asyncio.to_thread(a.salva, pid, f)
        n = sum(len(p.vignette) for p in nuove)
        l.log(f"Storia divisa in {len(nuove)} pagine e {n} vignette: le descrizioni si trasformano in prompt "
              "quando generi", "ok")
        app.bus.pubblica({"tipo": "fumetto", "progetto": pid, "vignetta": None})
        return {"pagine": len(nuove), "vignette": n}
    return app.gestore.avvia("fumetto_storia", "Dalla storia alle vignette", lavoro, progetto=pid).dict()
