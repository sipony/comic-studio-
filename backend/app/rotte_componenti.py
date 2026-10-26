"""API dei componenti di ComfyUI che Comic Studio installa da solo (IPAdapter Plus), dopo conferma."""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from . import componenti as comp
from .jobs import Lavoro

rotte = APIRouter(prefix="/api/componenti")


def _app(req: Request):
    return req.app.state.app


async def controlla(app, pubblica: bool = True) -> dict:
    """Quali componenti mancano (sul disco e, se ComfyUI è acceso, tra quelli che ComfyUI vede)."""
    comfy_dir = app.impostazioni.valori.comfy_dir or app.comfy.cartella
    modelli = nodi = None
    if app.comfy.connesso:
        try:
            modelli = await app.modelli()
            nodi = set((await app.object_info(ricarica=True)).keys())
        except Exception:  # noqa: BLE001 - si guarda solo il disco
            modelli = nodi = None
    s = await asyncio.to_thread(comp.controlla, comfy_dir, modelli, nodi)
    lavoro = next((l for l in app.gestore.attivi() if l.tipo == "componenti"), None)
    dati = s.dict() | {"chiedi": app.impostazioni.valori.chiedi_componenti, "lavoro": lavoro.id if lavoro else None,
                       "comfy_avviato_da_noi": app.comfy_pid is not None, "comfy_connesso": app.comfy.connesso,
                       "messaggio_spazio": comp.testo_spazio(s) if not s.basta_spazio else None}
    app.componenti = dati
    if pubblica:
        app.bus.pubblica({"tipo": "componenti", "dati": dati})
    return dati


@rotte.get("")
async def stato(req: Request):
    return await controlla(_app(req))


class Chiedi(BaseModel):
    chiedi: bool


@rotte.post("/chiedi")
async def chiedi(dati: Chiedi, req: Request):
    """«Non chiedere più» (o di nuovo sì) all'apertura."""
    app = _app(req)
    app.impostazioni.aggiorna(chiedi_componenti=dati.chiedi)
    return await controlla(app)


@rotte.post("/installa")
async def installa(req: Request):
    app = _app(req)
    s = await controlla(app, pubblica=False)
    if s["errore"]:
        raise HTTPException(409, s["errore"])
    if not s["mancanti"]:
        raise HTTPException(400, "IPAdapter Plus è già installato.")
    if not s["basta_spazio"]:
        raise HTTPException(409, s["messaggio_spazio"])
    attivo = next((l for l in app.gestore.attivi() if l.tipo == "componenti"), None)
    if attivo:
        return attivo.dict()
    return app.gestore.avvia("componenti", "Installazione di IPAdapter Plus", lambda l: _installa(app, l)).dict()


async def _installa(app, l: Lavoro):
    s = await controlla(app, pubblica=False)          # di nuovo: nel frattempo può essere cambiato qualcosa
    if not s["basta_spazio"]:
        raise comp.ErroreComponenti(s["messaggio_spazio"])
    base = Path(s["comfy_dir"])
    mancanti = s["mancanti"]
    l.log(f"Installo in {base}: " + ", ".join(f"{c['nome']} ({comp.gb(c['byte'])} GB)" for c in mancanti))
    nodo = False
    for i, c in enumerate(mancanti):
        l.controlla()

        def avanza(v: float, t: str, i=i):
            l.avanza(0.02 + 0.9 * (i + max(v, 0)) / len(mancanti), t)
        if c["tipo"] == "nodo":
            come = await asyncio.to_thread(comp.installa_nodo, c, base, avanza)
            l.log(f"{c['nome']} installato in custom_nodes ({come})", "ok")
            nodo = True
        else:
            dest = base / c["cartella"] / c["file"]
            await asyncio.to_thread(comp.scarica, c, dest, avanza, lambda: l.annullato)
            l.log(f"{c['nome']} scaricato: {dest}", "ok")
    riavvio = None
    if nodo:
        altri = [x for x in app.gestore.attivi() if x.id != l.id]
        if app.comfy_pid and not altri:
            l.avanza(0.94, "riavvio ComfyUI per caricare il nodo")
            l.log("Riavvio ComfyUI per caricare il nodo IPAdapter")
            r = app.riavvia_comfy()
            while r.stato in ("in_coda", "in_corso"):
                await asyncio.sleep(0.3)
            riavvio = "fatto" if r.stato == "completato" else "non riuscito"
            if r.stato != "completato":
                l.log(f"Riavvio di ComfyUI non riuscito: {r.errore}. Riavvialo da Sistema → Connessione.", "avviso")
        elif app.comfy.connesso or app.comfy_pid:
            riavvio = "a_mano"
            l.log("Riavvia ComfyUI per caricare il nodo IPAdapter"
                  + (" quando finiscono gli altri lavori." if app.comfy_pid else
                     ": è aperto fuori da Comic Studio, chiudilo e riaprilo (o premi Avvia in Sistema → Connessione)."),
                  "avviso")
    dopo = await controlla(app)
    if not dopo["mancanti"] and not dopo["da_caricare"]:
        l.log("IPAdapter Plus pronto: il dataset userà il riferimento per far somigliare i volti", "ok")
    return {"installati": [c["id"] for c in mancanti], "riavvio": riavvio, "stato": dopo}
