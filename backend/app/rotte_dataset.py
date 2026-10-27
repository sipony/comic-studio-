"""API e lavori dello Step 1 (Dataset): libreria dei workflow, configurazione, generazione, galleria, selezione."""
from __future__ import annotations

import asyncio
import json
import random
import re
import time
from pathlib import Path
from typing import Literal

import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask
from pydantic import BaseModel, Field

from .comfy.client import ComfyErrore
from . import pose as libreria_pose
from .dataset import (ArchivioDataset, ConfigDataset, InfoImmagine, componi, con_posa, crea_variante,
                      modello_positivo, pose_scelte, scegli_controlnet_posa, tag_qualita, valori_prompt)
from .jobs import Lavoro
from .projects import ErroreProgetto
from .settings import cartella_dati
from .somiglianza import scegli, valutatore
from .esclusione import escludi, titolo as titolo_nodo
from .modelinfo import famiglia_da_nome
from .workflows import (ErroreWorkflow, aggiungi_posa, analizza, applica, controlla_ruoli, guide_identita, img2img,
                        normalizza, per_invio)

rotte = APIRouter(prefix="/api/progetti/{pid}")


def _app(req: Request):
    return req.app.state.app


def _archivio(req: Request) -> ArchivioDataset:
    return ArchivioDataset(_app(req).progetti)


# ---------------------------------------------------------------- libreria dei workflow

@rotte.get("/workflows")
async def elenco_workflow(pid: str, req: Request):
    return [_riassunto(v) for v in _archivio(req).elenco_workflow(pid)]


def _riassunto(v) -> dict:
    a = analizza(v.workflow)
    return {"id": v.id, "nome": v.nome, "origine": v.origine, "creato": v.creato, "ruoli": v.ruoli,
            "avvisi": v.avvisi, "nodi": len(v.workflow), "checkpoint": a.checkpoint, "lora": a.lora,
            "parametri": v.parametri}


@rotte.post("/workflows", status_code=201)
async def carica_workflow(pid: str, req: Request, file: UploadFile = File(...), nome: str = Form("")):
    app = _app(req)
    try:
        dati = json.loads((await file.read()).decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise HTTPException(400, "Il file non è un JSON valido") from None
    object_info = None
    if isinstance(dati, dict) and isinstance(dati.get("nodes"), list):
        try:
            object_info = await app.object_info()
        except ComfyErrore:
            object_info = None
    try:
        wf, avvisi = normalizza(dati, object_info)
    except ErroreWorkflow as e:
        raise HTTPException(400, str(e)) from None
    nome = nome or Path(file.filename or "workflow").stem
    v, a = _archivio(req).aggiungi_workflow(pid, nome, file.filename or "workflow.json", wf, avvisi)
    app.bus.log(f"Workflow «{v.nome}» caricato: {len(wf)} nodi" + (f", {len(v.avvisi)} avvisi" if v.avvisi else ""), "ok")
    for x in v.avvisi:
        app.bus.log(f"Workflow «{v.nome}»: {x}", "avviso")
    return _riassunto(v)


class ParametriIntegrato(BaseModel):
    checkpoint: str
    ipadapter: str | None = None        # senza IPAdapter: txt2img
    clip_vision: str | None = None
    lora_stile: str | None = None
    forza_stile: float = Field(0.6, ge=0, le=2)
    peso_ipadapter: float = Field(0.7, ge=0, le=2)
    fine_ipadapter: float = Field(0.8, ge=0.1, le=1)
    passi: int = Field(30, ge=1, le=150)
    cfg: float = Field(6.5, ge=1, le=30)
    sampler: str = "euler_ancestral"
    scheduler: str = "karras"


@rotte.post("/workflows/integrato", status_code=201)
async def crea_integrato(pid: str, dati: ParametriIntegrato, req: Request):
    v = _archivio(req).workflow_integrato(pid, dati.model_dump())
    _app(req).bus.log(f"Creato il workflow «{v.nome}»", "ok")
    return _riassunto(v)


@rotte.get("/workflows/{wid}")
async def dettaglio_workflow(pid: str, wid: str, req: Request):
    v = _archivio(req).leggi_workflow(pid, wid)
    a = analizza(v.workflow)
    return {**_riassunto(v), "analisi": a.dict(), "workflow": v.workflow}


class ModificaWorkflow(BaseModel):
    nome: str | None = None
    ruoli: dict[str, str | None] | None = None


@rotte.patch("/workflows/{wid}")
async def modifica_workflow(pid: str, wid: str, dati: ModificaWorkflow, req: Request):
    a = _archivio(req)
    v = a.leggi_workflow(pid, wid)
    if dati.nome:
        v = a.rinomina_workflow(pid, wid, dati.nome)
    if dati.ruoli is not None:
        v = a.imposta_ruoli_workflow(pid, wid, dati.ruoli)
    return _riassunto(v)


@rotte.delete("/workflows/{wid}", status_code=204)
async def elimina_workflow(pid: str, wid: str, req: Request):
    _archivio(req).elimina_workflow(pid, wid)


@rotte.get("/workflows/{wid}/scarica")
async def scarica_workflow(pid: str, wid: str, req: Request):
    v = _archivio(req).leggi_workflow(pid, wid)
    return per_invio(v.workflow)


# ---------------------------------------------------------------- configurazione

@rotte.get("/personaggi/{cid}/dataset")
async def stato_dataset(pid: str, cid: str, req: Request):
    a = _archivio(req)
    _, pers = a.personaggio(pid, cid)
    config = a.config(pid, cid)
    return {"config": config.model_dump(), "riepilogo": a.riepilogo(pid, cid),
            "origine": coerenza(a, pid, pers.origine, config)}


def coerenza(a: ArchivioDataset, pid: str, origine: dict | None, config: ConfigDataset) -> dict | None:
    """Le scelte delle proposte da cui viene il riferimento e se il workflow del dataset le rispetta."""
    if not origine:
        return None
    checkpoint = lora = None
    if config.workflow:
        try:
            an = analizza(a.leggi_workflow(pid, config.workflow).workflow)
            checkpoint, lora = an.checkpoint, an.lora
        except Exception:  # noqa: BLE001 - workflow sparito dalla libreria
            pass
    stesso_ck = checkpoint == origine["checkpoint"]
    stessa_lora = not origine.get("lora_stile") or origine["lora_stile"] in (lora or [])
    return {"ricetta": origine, "checkpoint_workflow": checkpoint, "coerente": bool(stesso_ck and stessa_lora)}


@rotte.post("/personaggi/{cid}/dataset/confronto")
async def confronto(pid: str, cid: str, c: ConfigDataset, req: Request):
    """La configurazione (anche non salvata) confrontata con la proposta scelta come riferimento; null se il
    riferimento non viene da una proposta."""
    from .coerenza import confronta
    from .proposte import ArchivioProposte
    a = _archivio(req)
    _, pers = a.personaggio(pid, cid)
    scelta = next((p for p in ArchivioProposte(a.progetti).elenco(pid, cid) if p.scelta), None)
    if not scelta:
        return None
    wf, checkpoint, lora = None, None, []
    if c.workflow:
        try:
            wf = a.leggi_workflow(pid, c.workflow).workflow
            an = analizza(wf)
            checkpoint, lora = an.checkpoint, an.lora
        except Exception:  # noqa: BLE001 - workflow sparito dalla libreria
            wf = None
    return confronta(scelta, pers, c, wf, checkpoint, lora)


@rotte.post("/personaggi/{cid}/dataset/come-proposte")
async def come_proposte(pid: str, cid: str, req: Request):
    """Usa per il dataset le stesse scelte (checkpoint, LoRA di stile, stile, negativo) delle proposte."""
    app = _app(req)
    a = _archivio(req)
    _, pers = a.personaggio(pid, cid)
    if not pers.origine:
        raise HTTPException(400, f"Il riferimento di {pers.nome} non viene da una proposta di Comic Studio.")
    return await prepara_come_proposte(app, pid, cid, pers.origine)


async def prepara_come_proposte(app, pid: str, cid: str, ricetta: dict) -> dict:
    a = ArchivioDataset(app.progetti)
    modelli = await app.modelli()
    c, voce, avvisi = await asyncio.to_thread(a.come_proposte, pid, cid, ricetta, modelli)
    _, pers = a.personaggio(pid, cid)
    app.bus.log(f"Dataset di {pers.nome}: workflow «{voce.nome}» con le stesse scelte delle proposte"
                + (f" (stile: {c.stile})" if c.stile else ""), "ok")
    for x in avvisi:
        app.bus.log(x, "avviso")
    app.bus.pubblica({"tipo": "dataset", "progetto": pid, "personaggio": cid, "azione": "config"})
    return {"config": c.model_dump(), "workflow": _riassunto(voce), "avvisi": avvisi,
            "origine": coerenza(a, pid, ricetta, c)}


@rotte.put("/personaggi/{cid}/dataset/config")
async def salva_config(pid: str, cid: str, c: ConfigDataset, req: Request):
    return _archivio(req).salva_config(pid, cid, c).model_dump()


@rotte.post("/personaggi/{cid}/dataset/esempi")
async def esempi(pid: str, cid: str, c: ConfigDataset, req: Request, n: int = 4):
    return _archivio(req).esempi_prompt(pid, cid, c, max(1, min(n, 12)))


# ---------------------------------------------------------------- immagini

@rotte.get("/personaggi/{cid}/dataset/immagini")
async def immagini(pid: str, cid: str, req: Request):
    return [v.model_dump() for v in _archivio(req).immagini(pid, cid)]


@rotte.get("/personaggi/{cid}/dataset/immagini/{file}")
async def immagine(pid: str, cid: str, file: str, req: Request, anteprima: bool = False):
    f = await asyncio.to_thread(_archivio(req).file_immagine, pid, cid, file, anteprima)
    return FileResponse(f, headers={"Cache-Control": "max-age=3600"})


class Stato(BaseModel):
    stato: Literal["tenuta", "scartata"] | None


@rotte.patch("/personaggi/{cid}/dataset/immagini/{file}")
async def imposta_stato(pid: str, cid: str, file: str, dati: Stato, req: Request):
    v = _archivio(req).imposta_stato(pid, cid, file, dati.stato)
    _app(req).bus.pubblica({"tipo": "dataset", "progetto": pid, "personaggio": cid, "azione": "stato",
                            "immagine": v.model_dump()})
    return v.model_dump()


class Elimina(BaseModel):
    file: list[str] | None = None
    scartate: bool = False
    definitivo: bool = False          # cancella dal disco invece di spostare nel cestino (dopo il download)


@rotte.post("/personaggi/{cid}/dataset/elimina")
async def elimina(pid: str, cid: str, dati: Elimina, req: Request):
    a = _archivio(req)
    files = dati.file
    if dati.scartate:
        files = [v.file for v in a.immagini(pid, cid) if v.stato == "scartata"]
    prima = a.spazio(pid, cid)
    n = await asyncio.to_thread(a.elimina_immagini, pid, cid, files, dati.definitivo)
    liberati = prima - a.spazio(pid, cid)
    if dati.definitivo:
        _app(req).bus.log(f"{n} immagini cancellate dal disco: liberati {_mb(liberati)}", "avviso" if n else "info")
    else:
        _app(req).bus.log(f"{n} immagini spostate nel cestino", "avviso" if n else "info")
    _app(req).bus.pubblica({"tipo": "dataset", "progetto": pid, "personaggio": cid, "azione": "elenco"})
    return {"eliminate": n, "liberati": liberati if dati.definitivo else 0}


def _mb(byte: int) -> str:
    if byte >= 1e9:
        return f"{byte / 1e9:.1f} GB"
    return f"{byte / 1e6:.0f} MB" if byte >= 1e6 else f"{byte / 1e3:.0f} KB"


@rotte.get("/personaggi/{cid}/dataset/cestino")
async def cestino(pid: str, cid: str, req: Request):
    return _archivio(req).cestino(pid, cid)


@rotte.post("/personaggi/{cid}/dataset/cestino/svuota")
async def svuota_cestino(pid: str, cid: str, req: Request):
    """Cancella dal disco le immagini di questo dataset che erano nel cestino."""
    r = await asyncio.to_thread(_archivio(req).svuota_cestino, pid, cid)
    _app(req).bus.log(f"Cestino del dataset svuotato: {r['immagini']} immagini, liberati {_mb(r['byte'])}", "ok")
    _app(req).bus.pubblica({"tipo": "dataset", "progetto": pid, "personaggio": cid, "azione": "elenco"})
    return r


class Esporta(BaseModel):
    file: list[str] | None = None     # None = tutte


@rotte.post("/personaggi/{cid}/dataset/esporta")
async def esporta(pid: str, cid: str, dati: Esporta, req: Request):
    """Prepara lo ZIP delle immagini (lavoro); poi si scarica da /esportazioni/<nome>."""
    app = _app(req)
    a = _archivio(req)
    _, pers = a.personaggio(pid, cid)

    async def lavoro(l: Lavoro):
        r = await asyncio.to_thread(a.esporta, pid, cid, dati.file, l.avanza, l.controlla)
        l.log(f"ZIP pronto: {r['immagini']} immagini, {_mb(r['byte'])}", "ok")
        return r
    n = len(dati.file) if dati.file is not None else len(a.immagini(pid, cid))
    return app.gestore.avvia("dataset_esporta", f"ZIP del dataset di {pers.nome} ({n} immagini)", lavoro,
                             progetto=pid).dict()


@rotte.get("/personaggi/{cid}/dataset/esportazioni/{nome}")
async def scarica_esportazione(pid: str, cid: str, nome: str, req: Request):
    """Lo ZIP preparato; dopo l'invio viene tolto dal disco (si può sempre rifare)."""
    f = _archivio(req).file_esportazione(pid, cid, nome)
    return FileResponse(f, media_type="application/zip", filename=nome,
                        background=BackgroundTask(f.unlink, missing_ok=True))


# ---------------------------------------------------------------- nodi staccati

async def _info_nodi(app) -> dict | None:
    """Definizioni dei nodi di ComfyUI (tipi di ingressi e uscite), se è collegato."""
    if not app.comfy.connesso:
        return None
    try:
        return await app.object_info()
    except Exception:  # noqa: BLE001 - senza si usano i nodi più comuni
        return None


def _classe_latente(checkpoint: str | None) -> str:
    return "EmptySD3LatentImage" if famiglia_da_nome(checkpoint or "") in ("flux", "sd3") else "EmptyLatentImage"


def prova_esclusione(a: ArchivioDataset, pid: str, config: ConfigDataset, info: dict | None):
    """Cosa succede al workflow staccando i nodi scelti: ricollegamenti, nodi staccati in automatico, problemi."""
    voce, ruoli = a.ruoli_effettivi(pid, config)
    libera = bool(img2img(voce.workflow, ruoli.riferimento)) and config.composizione == "libera"
    w = applica(voce.workflow, ruoli, dimensioni=(1024, 1024), modifiche=config.modifiche, composizione_libera=libera,
                classe_latente=_classe_latente(analizza(voce.workflow).checkpoint))
    return escludi(w, config.disattivati, info, protetti=(ruoli.seme, ruoli.salva, ruoli.positivo))


@rotte.post("/personaggi/{cid}/dataset/esclusione")
async def esclusione(pid: str, cid: str, c: ConfigDataset, req: Request):
    """Anteprima dei nodi staccati con la configurazione indicata (anche non ancora salvata)."""
    if not c.workflow:
        raise HTTPException(400, "Scegli prima un workflow.")
    info = await _info_nodi(_app(req))
    return prova_esclusione(_archivio(req), pid, c, info).dict() | {"tipi_da_comfy": info is not None}


# ---------------------------------------------------------------- generazione

class Genera(BaseModel):
    quantita: int = Field(ge=1, le=2000)
    sostituisci: bool = False
    # «una immagine per posa»: una figura intera per ognuna delle pose scelte (la quantità non conta)
    una_per_posa: bool = False


async def elenco_controlnet(app, checkpoint: str | None) -> list[dict]:
    """I ControlNet che ComfyUI vede, con l'architettura (dal file se è nella cartella di ComfyUI, se no dal nome) e
    se vanno bene con il checkpoint."""
    from .modelinfo import architettura_checkpoint, architettura_controlnet
    elenco = (await app.modelli()).get("controlnet") or []
    base = app.impostazioni.valori.comfy_dir or app.comfy.cartella
    serve = architettura_checkpoint(checkpoint or "")
    out = []
    for n in elenco:
        f = Path(base) / "models" / "controlnet" / n if base else None
        arch = await asyncio.to_thread(architettura_controlnet, n, f)
        out.append({"nome": n, "architettura": arch, "compatibile": None if arch is None else arch == serve})
    return out


async def controlnet_posa(app, config: ConfigDataset, checkpoint: str | None) -> str:
    """Il ControlNet da usare per le pose guidate (quello scelto, altrimenti il primo OpenPose della stessa
    architettura del checkpoint che ComfyUI vede)."""
    from .modelinfo import architettura_checkpoint
    elenco = await elenco_controlnet(app, checkpoint)
    nomi = [x["nome"] for x in elenco]
    serve = architettura_checkpoint(checkpoint or "")
    if config.pose.controlnet:
        if nomi and config.pose.controlnet not in nomi:
            raise HTTPException(400, f"Il ControlNet «{config.pose.controlnet}» non c'è più in ComfyUI: scegline un "
                                     "altro in Dataset → Pose guidate.")
        x = next((x for x in elenco if x["nome"] == config.pose.controlnet), None)
        if x and x["compatibile"] is False:
            raise HTTPException(400, f"Il ControlNet «{config.pose.controlnet}» è per {NOMI_ARCH.get(x['architettura'], x['architettura'])}, "
                                     f"ma il checkpoint ({checkpoint}) è {NOMI_ARCH.get(serve, serve)}: scegli un ControlNet "
                                     "OpenPose SDXL in Dataset → Pose guidate (o «Automatico»).")
        return config.pose.controlnet
    scelto = scegli_controlnet_posa(nomi, famiglia_da_nome(checkpoint or ""),
                                    {x["nome"]: x["architettura"] for x in elenco})
    if not scelto:
        altri = [x["nome"] for x in elenco if x["compatibile"] is False]
        raise HTTPException(400, "Per le pose guidate serve un ControlNet OpenPose "
                                 f"{NOMI_ARCH.get(serve, serve)}: installalo da Dataset → Pose guidate (pulsante "
                                 "«Installa»), oppure mettilo in ComfyUI/models/controlnet."
                                 + (f" Quelli che hai ({', '.join(altri)}) sono per un'altra architettura e farebbero "
                                    "fallire il KSampler." if altri else ""))
    return scelto


NOMI_ARCH = {"sd15": "SD 1.5", "sdxl": "SDXL (anche Pony, Illustrious, NoobAI)", "sd2": "SD 2", "flux": "Flux"}


def spiega_errore_posa(e: Exception, controlnet: str | None) -> Exception:
    """«mat1 and mat2 shapes cannot be multiplied (…x2048 and 768x…)»: ControlNet di un'altra architettura."""
    testo = str(e)
    if controlnet and "mat1 and mat2 shapes cannot be multiplied" in testo:
        return ComfyErrore(f"Il ControlNet «{controlnet}» non è per questo checkpoint (di solito: ControlNet per SD 1.5 "
                           "con un checkpoint SDXL, Pony o Illustrious). Scegli un ControlNet OpenPose SDXL in Dataset "
                           f"→ Pose guidate, o installalo da lì. Dettaglio di ComfyUI: {testo[:200]}")
    return e


@rotte.get("/personaggi/{cid}/dataset/controlnet")
async def controlnet_disponibili(pid: str, cid: str, req: Request):
    """I ControlNet con l'architettura, quali vanno bene con il checkpoint del workflow e quale si userebbe da solo."""
    a = _archivio(req)
    c = a.config(pid, cid)
    checkpoint = analizza(a.leggi_workflow(pid, c.workflow).workflow).checkpoint if c.workflow else None
    elenco = await elenco_controlnet(_app(req), checkpoint)
    auto = scegli_controlnet_posa([x["nome"] for x in elenco], famiglia_da_nome(checkpoint or ""),
                                  {x["nome"]: x["architettura"] for x in elenco})
    from .modelinfo import architettura_checkpoint
    return {"elenco": elenco, "automatico": auto, "checkpoint": checkpoint,
            "serve": architettura_checkpoint(checkpoint or "")}


def inquadratura_intera(config: ConfigDataset):
    """L'inquadratura della figura intera (per «una immagine per posa»): quella che lo dice, altrimenti la più alta."""
    inq = config.varianti.inquadrature
    return next((i for i in inq if libreria_pose.taglio(f"{i.testo} {i.nome}") == "intera"
                 and re.search(r"full body|figura intera", f"{i.testo} {i.nome}", re.I)),
                max(inq, key=lambda i: i.altezza / i.larghezza))


@rotte.post("/personaggi/{cid}/dataset/genera")
async def genera(pid: str, cid: str, dati: Genera, req: Request):
    app = _app(req)
    a = _archivio(req)
    progetto, pers = a.personaggio(pid, cid)
    config = a.config(pid, cid)
    voce, ruoli = a.ruoli_effettivi(pid, config)
    errori = controlla_ruoli(voce.workflow, ruoli)
    if errori:
        raise HTTPException(400, "Ruoli del workflow non validi: " + "; ".join(errori))
    if not app.comfy.connesso:
        raise HTTPException(409, "ComfyUI non è connesso: avvialo e riprova.")
    info_nodi = await _info_nodi(app) if config.disattivati else None
    usa_riferimento = bool(ruoli.riferimento)
    if config.disattivati:
        prova = prova_esclusione(a, pid, config, info_nodi)
        if prova.problemi:
            raise HTTPException(400, "Con i nodi staccati il workflow non funziona: " + " ".join(prova.problemi))
        usa_riferimento = usa_riferimento and ruoli.riferimento not in prova.esclusi
        if usa_riferimento:     # il riferimento serve ancora? (staccato IPAdapter, il suo LoadImage resta senza uso)
            from .workflows import senza_inutili
            usa_riferimento = ruoli.riferimento in senza_inutili(prova.wf)
    if usa_riferimento and not pers.riferimento:
        raise HTTPException(400, f"{pers.nome} non ha un'immagine di riferimento: caricala nella pagina Personaggi.")
    con_pose = config.pose.attive or dati.una_per_posa
    pose = pose_scelte(config.pose) if con_pose else []
    controlnet = None
    if con_pose:
        if not pose:
            raise HTTPException(400, "Scegli almeno una posa in Dataset → Pose guidate.")
        controlnet = await controlnet_posa(app, config, analizza(voce.workflow).checkpoint)
    quantita = len(pose) if dati.una_per_posa else dati.quantita

    async def lavoro(l: Lavoro):
        if dati.sostituisci:
            n = a.elimina_immagini(pid, cid)
            if n:
                l.log(f"{n} immagini precedenti spostate nel cestino")
            app.bus.pubblica({"tipo": "dataset", "progetto": pid, "personaggio": cid, "azione": "elenco"})
        analisi = analizza(voce.workflow)
        checkpoint = analisi.checkpoint
        qualita = tag_qualita(checkpoint, config)
        da_rif = img2img(voce.workflow, ruoli.riferimento)
        libera = bool(da_rif) and (config.composizione == "libera" or con_pose)
        classe_latente = _classe_latente(checkpoint)
        if config.disattivati:
            l.log(f"Nodi staccati: {', '.join(titolo_nodo(voce.workflow, n) for n in prova.esclusi)}. "
                  + (f"Ricollegati: {'; '.join(x['testo'] for x in prova.collegamenti)}." if prova.collegamenti else ""))
        if con_pose:
            l.log(f"Pose guidate con {controlnet} (forza {config.pose.forza}, fino al {round(config.pose.fine * 100)}% "
                  f"dei passi): {len(pose)} pose"
                  + (", una immagine per posa a figura intera" if dati.una_per_posa else ", a turno"))
            if not guide_identita(voce.workflow, ruoli.riferimento) and not analisi.lora:
                l.log("Senza IPAdapter né LoRA del personaggio lo scheletro decide la posa ma non l'aspetto: per un "
                      "personaggio identico usa il workflow con IPAdapter («Rendi il dataset identico alle proposte»).",
                      "avviso")
        if libera:
            l.log("Il workflow è img2img: ogni immagine parte da zero con la posa e l'inquadratura della "
                  "variante, non da quelle del riferimento.")
            if not guide_identita(voce.workflow, ruoli.riferimento) and not analisi.lora:
                l.log("Nel workflow non ci sono né LoRA del personaggio né IPAdapter: senza la composizione del "
                      "riferimento il personaggio potrebbe non somigliare. Usa «Crea quello integrato» oppure "
                      "aggiungi un LoRA.", "avviso")
        elif da_rif:
            l.log("Composizione dal riferimento (img2img): tutte le immagini avranno la posa e l'inquadratura "
                  "dell'immagine di riferimento.", "avviso")
        rng = random.Random()
        conteggio: dict[str, int] = {}
        for v in a.immagini(pid, cid):
            if v.inquadratura:
                conteggio[v.inquadratura] = conteggio.get(v.inquadratura, 0) + 1
        nome_rif = None
        async with app.client() as client:
            if usa_riferimento:
                rif = app.progetti.file_riferimento(pid, cid)
                copia = rif.with_name(f"{pid}_{cid}_riferimento.png")
                copia.write_bytes(rif.read_bytes())
                nome_rif = await client.carica_immagine(copia)
                copia.unlink(missing_ok=True)
                l.log(f"Immagine di riferimento caricata in ComfyUI ({nome_rif})")
            rotazione = libreria_pose.Rotazione(pose)
            scheletri: dict[tuple, str] = {}
            cartella_pose = cartella_dati() / "tmp" / "pose"
            intera = inquadratura_intera(config) if dati.una_per_posa else None
            inizio = time.time()
            for k in range(quantita):
                l.controlla()
                numero = a.prossimo_numero(pid, cid)
                if intera:
                    var = crea_variante(config.varianti.model_copy(update={"inquadrature": [intera]}), conteggio, rng)
                else:
                    var = crea_variante(config.varianti, conteggio, rng)
                posa = None
                if con_pose:
                    t = libreria_pose.taglio(f"{var['inquadratura']} {var['_nome_inquadratura']}")
                    posa = pose[k % len(pose)] if intera else rotazione.prossima(t)
                    if posa:
                        var = con_posa(var, posa)
                val = valori_prompt(pers, var, qualita, config.stile, config.aspetto)
                positivo = componi(modello_positivo(config), val)
                negativo = componi(config.prompt_negativo, val)
                larghezza, altezza = (int(x) for x in var["_dimensioni"].split("x"))
                seme = rng.randrange(2 ** 48)
                wf = applica(voce.workflow, ruoli, riferimento=nome_rif, positivo=positivo, negativo=negativo,
                             seme=seme, dimensioni=(larghezza, altezza),
                             prefisso=f"comic_studio/{pid}/{cid}/dataset", modifiche=config.modifiche,
                             composizione_libera=libera, classe_latente=classe_latente,
                             disattivati=config.disattivati, info=info_nodi)
                if posa:
                    chiave = (posa.id, larghezza, altezza, t)
                    if chiave not in scheletri:
                        cartella_pose.mkdir(parents=True, exist_ok=True)
                        f = cartella_pose / f"{pid}_{cid}_posa_{posa.id}_{larghezza}x{altezza}_{t}.png"
                        f.write_bytes(libreria_pose.png(posa, larghezza, altezza, t))
                        scheletri[chiave] = await client.carica_immagine(f)
                        f.unlink(missing_ok=True)
                    aggiungi_posa(wf, controlnet, scheletri[chiave], config.pose.forza, 0.0, config.pose.fine)
                l.log(f"Immagine {k + 1}/{quantita} · {var['_nome_inquadratura']}"
                      + (f" · posa «{posa.nome}»" if posa else "") + f": {var['variante']}")

                def avanza(v, t, k=k):
                    l.avanza((k + v) / quantita, f"immagine {k + 1}/{quantita} · {t}")
                l.registra_workflow(wf, {"tipo": "dataset", "progetto": pid, "personaggio": cid,
                                         "workflow": config.workflow, "libera": libera,
                                         "posa": posa.id if posa else None})
                try:
                    uscite = await client.esegui(per_invio(wf), avanza, anteprima=l.imposta_anteprima)
                except ComfyErrore as e:
                    raise spiega_errore_posa(e, controlnet if posa else None) from None
                immagini_uscite = uscite.get(ruoli.salva) if ruoli.salva else None
                immagini_uscite = immagini_uscite or next(iter(uscite.values()), None)
                if not immagini_uscite:
                    raise ComfyErrore("ComfyUI non ha restituito immagini: controlla il nodo di salvataggio "
                                      "scelto nel workflow.")
                dati_img = await client.scarica(immagini_uscite[0])
                l.imposta_anteprima(dati_img, "image/png", finale=True)
                info = InfoImmagine(file=f"{numero:04d}.png", numero=numero, inquadratura=var["_nome_inquadratura"],
                                    variante=var["variante"], prompt=positivo, seme=seme,
                                    larghezza=larghezza, altezza=altezza, posa=posa.id if posa else "")
                await asyncio.to_thread(a.aggiungi_immagine, pid, cid, dati_img, info, wf)
                app.bus.pubblica({"tipo": "dataset", "progetto": pid, "personaggio": cid, "azione": "nuova",
                                  "immagine": info.model_dump()})
                trascorso = time.time() - inizio
                resto = trascorso / (k + 1) * (quantita - k - 1)
                l.avanza((k + 1) / quantita, f"{k + 1}/{quantita} fatte · mancano circa {_durata(resto)}")
        l.log(f"Generate {quantita} immagini di {pers.nome} in {_durata(time.time() - inizio)}", "ok")
        return {"generate": quantita}

    titolo = f"Dataset di {pers.nome}: " + (f"una immagine per posa ({quantita})" if dati.una_per_posa
                                             else f"{quantita} immagini")
    l = app.gestore.avvia("dataset_genera", titolo, lavoro,
                          progetto=pid, esclusivo=True)
    return l.dict()


def _durata(s: float) -> str:
    s = int(s)
    if s < 90:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min"
    return f"{s // 3600} h {s % 3600 // 60} min"


# ---------------------------------------------------------------- selezione automatica

class Seleziona(BaseModel):
    quante: int | None = Field(default=None, ge=1, le=500)
    soglia_doppioni: float = Field(default=0.96, ge=0.5, le=1.0)


@rotte.post("/personaggi/{cid}/dataset/seleziona")
async def seleziona(pid: str, cid: str, dati: Seleziona, req: Request):
    app = _app(req)
    a = _archivio(req)
    _, pers = a.personaggio(pid, cid)
    config = a.config(pid, cid)
    voci = a.immagini(pid, cid)
    if not voci:
        raise HTTPException(400, "Non ci sono immagini da selezionare: genera prima il dataset.")
    quante = dati.quante or config.da_tenere

    async def lavoro(l: Lavoro):
        cartella = a.cartella(pid, cid) / "generate"
        file = [cartella / v.file for v in voci]
        rif = None
        if pers.riferimento:
            try:
                rif = app.progetti.file_riferimento(pid, cid)
            except ErroreProgetto:
                rif = None
        l.avanza(0.02, "preparo il modello di somiglianza")
        val = await asyncio.to_thread(valutatore, cartella_dati() / "modelli",
                                      lambda v, t: l.avanza(0.02 + v * 0.3, t), l.log)
        l.log(f"Somiglianza calcolata con: {val.nome}")
        percorsi = ([rif] if rif else []) + file
        E = await asyncio.to_thread(val.vettori, percorsi, lambda v, t: l.avanza(0.35 + v * 0.6, t))
        if rif is not None:
            riferimento, E = E[0], E[1:]
        else:
            l.log("Nessuna immagine di riferimento: uso la coerenza tra le immagini.", "avviso")
            riferimento = E.mean(axis=0)
            riferimento = riferimento / (np.linalg.norm(riferimento) or 1)
        punteggi = (E @ riferimento).tolist()
        quote = {i.nome: i.quota for i in config.varianti.inquadrature}
        gruppi = [v.inquadratura for v in voci]
        forzati = {i for i, v in enumerate(voci) if v.manuale and v.stato == "tenuta"}
        esclusi = {i for i, v in enumerate(voci) if v.manuale and v.stato == "scartata"}
        scelti = scegli(punteggi, E, gruppi, quante, quote, dati.soglia_doppioni, esclusi, forzati)
        tenute = {voci[i].file for i in scelti}
        a.imposta_selezione(pid, cid, {v.file: p for v, p in zip(voci, punteggi)}, tenute)
        simili = E @ E.T
        doppioni = int(np.triu(simili > dati.soglia_doppioni, k=1).sum())
        l.log(f"Tenute {len(tenute)} immagini su {len(voci)} (le più somiglianti, distribuite per inquadratura"
              + (f"; {doppioni} coppie quasi identiche escluse" if doppioni else "") + ")", "ok")
        app.bus.pubblica({"tipo": "dataset", "progetto": pid, "personaggio": cid, "azione": "elenco"})
        return {"tenute": len(tenute)}

    l = app.gestore.avvia("dataset_seleziona", f"Selezione del dataset di {pers.nome}", lavoro, progetto=pid)
    return l.dict()


# ---------------------------------------------------------------- definizioni dei nodi (per l'editor)

rotte_comfy = APIRouter(prefix="/api/comfy")


@rotte_comfy.get("/nodi")
async def nodi(req: Request, classi: str, ricarica: bool = False):
    info = await _app(req).object_info(ricarica)
    out = {}
    for c in classi.split(","):
        c = c.strip()
        if c in info:
            d = info[c]
            out[c] = {"input": d.get("input", {}), "input_order": d.get("input_order"),
                      "display_name": d.get("display_name"), "category": d.get("category")}
    return out


# ---------------------------------------------------------------- libreria delle pose

rotte_pose = APIRouter(prefix="/api/pose")


@rotte_pose.get("")
async def elenco_pose():
    return {"pose": [libreria_pose.info(p) for p in libreria_pose.elenco(con_specchiate=True)],
            "tagli": list(libreria_pose.TAGLI)}


@rotte_pose.get("/{id_posa}/scheletro")
async def scheletro(id_posa: str, larghezza: int = 416, altezza: int = 608, taglio: str = "intera"):
    """Lo scheletro OpenPose di una posa (PNG), come quello che riceve il ControlNet."""
    try:
        p = libreria_pose.trova(id_posa)
    except KeyError:
        raise HTTPException(404, f"Posa «{id_posa}» non trovata") from None
    if taglio not in libreria_pose.TAGLI:
        raise HTTPException(400, f"Taglio non valido: {', '.join(libreria_pose.TAGLI)}")
    if not (64 <= larghezza <= 2048 and 64 <= altezza <= 2048):
        raise HTTPException(400, "Dimensioni tra 64 e 2048")
    dati = await asyncio.to_thread(libreria_pose.png, p, larghezza, altezza, taglio)
    return Response(dati, media_type="image/png", headers={"Cache-Control": "max-age=86400"})


# ---------------------------------------------------------------- grafi salvati e confronto con la proposta

NOTA_RICOSTRUITO = {
    "proposta": "Proposta fatta prima della 0.23: il workflow è ricostruito dalla sua ricetta, dal prompt e dal seme con "
                "lo stesso codice che l'ha generata.",
    "immagine": "Immagine fatta prima della 0.23: il workflow è ricostruito con la configurazione attuale del dataset e "
                "il prompt, il seme e le dimensioni dell'immagine (se nel frattempo hai cambiato workflow o nodi, "
                "allora era diverso).",
}


async def pacchetto_grafo(app, wf: dict, titolo: str, ricostruito: bool, tipo: str, url_json: str) -> dict:
    """Un workflow salvato nella stessa forma del grafo di un lavoro (sola lettura), per la stessa vista."""
    from .grafo import descrivi, riassunto
    info = await _info_nodi(app)
    return {"lavoro": {"id": "", "titolo": titolo, "tipo": tipo}, "n": 1, "riassunto": riassunto(wf), "workflow": wf,
            "grafo": descrivi(wf, info), "url_json": url_json,
            "impostazioni": {"sorgente": None, "campi": {}}, "ricostruito": ricostruito,
            "nota": NOTA_RICOSTRUITO[tipo] if ricostruito else None}


def _json_scaricabile(wf: dict, nome: str) -> Response:
    return Response(json.dumps(per_invio(wf), indent=2, ensure_ascii=False), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{nome}"'})


@rotte.get("/personaggi/{cid}/dataset/immagini/{file}/workflow")
async def workflow_immagine(pid: str, cid: str, file: str, req: Request, formato: str = "grafo"):
    a = _archivio(req)
    wf, ricostruito = a.workflow_immagine(pid, cid, file)
    if formato == "json":
        return _json_scaricabile(wf, f"comic-studio-{cid}-dataset-{Path(file).stem}.json")
    _, pers = a.personaggio(pid, cid)
    return await pacchetto_grafo(_app(req), wf, f"Dataset di {pers.nome} · immagine {Path(file).stem}", ricostruito,
                                 "immagine", f"/api/progetti/{pid}/personaggi/{cid}/dataset/immagini/{file}/workflow"
                                             "?formato=json")


@rotte.get("/personaggi/{cid}/dataset/immagini/{file}/confronto")
async def confronto_grafi(pid: str, cid: str, file: str, req: Request):
    """Il grafo della proposta da cui è nato il personaggio (il riferimento) e quello di questa immagine del dataset,
    con le differenze nodo per nodo (i prompt tag per tag). Seme e nome dei file cambiano sempre e non si contano."""
    from .grafo import confronta
    from .proposte import ArchivioProposte
    app = _app(req)
    a = _archivio(req)
    _, pers = a.personaggio(pid, cid)
    ap = ArchivioProposte(app.progetti)
    scelta = next((p for p in ap.elenco(pid, cid) if p.scelta), None)
    if scelta is None:
        raise HTTPException(404, f"L'immagine di riferimento di {pers.nome} non viene da una proposta: non c'è un "
                                 "workflow di partenza da confrontare.")
    wp, rp = ap.workflow_di(pid, cid, scelta.file)
    wd, rd = a.workflow_immagine(pid, cid, file)
    d = confronta(wp, wd, "proposta", "dataset", ignora=("seed", "noise_seed", "filename_prefix", "image"))
    base = f"/api/progetti/{pid}/personaggi/{cid}"
    return {"proposta": await pacchetto_grafo(app, wp, f"Proposta scelta come riferimento · {scelta.file}", rp,
                                              "proposta", f"{base}/proposte/{scelta.file}/workflow?formato=json"),
            "immagine": await pacchetto_grafo(app, wd, f"Dataset · immagine {Path(file).stem}", rd, "immagine",
                                              f"{base}/dataset/immagini/{file}/workflow?formato=json"),
            "file_proposta": scelta.file, **d}


# ---------------------------------------------------------------- stessa persona, come le proposte

SFONDI_PROPOSTE = ["simple background, white background"]


def varianti_leggere(larghezza: int = 832, altezza: int = 1216):
    """Le varianti «come le proposte»: stessa risoluzione delle proposte, sfondo bianco, sguardo in camera,
    espressioni tranquille; cambiano solo posa, angolazione e quanto della figura si vede. Nelle proposte il
    personaggio resta lo stesso proprio perché il prompt e le dimensioni non cambiano: qui cambia il meno possibile."""
    from .dataset import Inquadratura, Varianti
    return Varianti(
        inquadrature=[Inquadratura(nome="figura intera", testo="full body", larghezza=larghezza, altezza=altezza,
                                   quota=0.5),
                      Inquadratura(nome="tre quarti", testo="cowboy shot", larghezza=larghezza, altezza=altezza,
                                   quota=0.3),
                      Inquadratura(nome="mezzo busto", testo="upper body", larghezza=larghezza, altezza=altezza,
                                   quota=0.2)],
        angolazioni=["front view", "front view", "front view", "three-quarter view", "three-quarter view",
                     "from side"],
        espressioni=["neutral expression", "neutral expression", "light smile", "smile", "serious", "closed mouth"],
        pose=["standing", "standing, contrapposto", "hands on hips", "hand on own hip", "arms crossed",
              "arms behind back", "walking", "waving", "hand up", "sitting"],
        sfondi=list(SFONDI_PROPOSTE))


def modello_come_proposte(extra: str = "") -> str:
    """Il prompt nell'ordine delle proposte (qualità, genere, solo, sguardo, espressione, sfondo, tratti, aspetto,
    tag in più, inquadratura, posa, angolazione, stile): le parti fisse sono le stesse delle proposte."""
    from .proposte import pulisci
    extra = pulisci(extra or "")
    return ("{qualita}, {genere}, solo, looking at viewer, {espressione}, {sfondo}, {descrizione}, {aspetto}"
            + (f", {extra}" if extra else "") + ", {inquadratura}, {posa}, {angolazione}, {stile}")


def carica_tagger(*a, **k):
    from .didascalie import carica_tagger as carica
    return carica(*a, **k)


@rotte.post("/personaggi/{cid}/dataset/somiglianza")
async def massima_somiglianza(pid: str, cid: str, req: Request):
    """«Stessa persona, come le proposte»: le proposte sembrano sempre la stessa persona perché nascono con lo stesso
    prompt, alle stesse dimensioni, con lo stesso workflow e senza nient'altro; cambia solo il seme. Il dataset fa lo
    stesso: workflow delle proposte (IPAdapter staccato, niente ControlNet), prompt nello stesso ordine, stessa
    risoluzione, sfondo bianco; cambiano poco posa, angolazione ed espressione. In più l'aspetto del riferimento letto
    dal tagger (le proposte cambiano divisa da un seme all'altro: così la divisa è quella scelta). Poi «Tieni le
    migliori» sceglie le più somiglianti al riferimento."""
    app = _app(req)
    a = _archivio(req)
    _, pers = a.personaggio(pid, cid)
    if not pers.riferimento:
        raise HTTPException(400, f"{pers.nome} non ha un'immagine di riferimento: caricala o scegli una proposta.")
    config = a.config(pid, cid)
    if not config.workflow and not pers.origine:
        raise HTTPException(400, "Scegli prima un workflow (o crea il personaggio dalle proposte).")

    async def lavoro(l: Lavoro):
        from .dataset import aspetto_da_tag
        from .didascalie import ConfigDidascalie
        from .proposte import DIMENSIONI
        fatto: list[str] = []
        origine = pers.origine or {}
        if origine.get("checkpoint"):
            # lo stesso workflow delle proposte (stesso checkpoint, LoRA, campionamento, negativo)
            c, voce, _ = a.come_proposte(pid, cid, origine, await app.modelli())
            fatto.append(f"workflow delle proposte: {voce.nome}")
        else:
            c = a.config(pid, cid)
            l.log(f"{pers.nome} non viene dalle proposte: tengo il workflow scelto e sistemo prompt e varianti.", "info")
        voce, _ = a.ruoli_effettivi(pid, c)
        # 1) aspetto dal riferimento
        l.avanza(0.02, "preparo il tagger")
        try:
            tagger = await asyncio.to_thread(carica_tagger, cartella_dati() / "modelli", ConfigDidascalie().modello,
                                             lambda v, t: l.avanza(0.02 + v * 0.6, t), l.log)
            rif = app.progetti.file_riferimento(pid, cid)
            tag = (await asyncio.to_thread(tagger.tagga, [rif])).get(rif.name, {})
            aspetto = aspetto_da_tag(tag, pers, c.stile)
            c.aspetto = ", ".join(aspetto)
            if aspetto:
                fatto.append(f"aspetto del riferimento nel prompt: {c.aspetto}")
            else:
                l.log("Il tagger non ha trovato nel riferimento tratti che la descrizione non dica già.", "info")
        except ErroreProgetto as e:
            l.log(f"Aspetto dal riferimento saltato: {e}", "avviso")
        l.controlla()
        # 2) prompt nell'ordine delle proposte e varianti leggere alla stessa risoluzione
        c.prompt_positivo = modello_come_proposte(origine.get("extra", ""))
        dim = DIMENSIONI.get(origine.get("inquadratura") or "", (832, 1216))
        dim = dim if dim[1] >= dim[0] else (832, 1216)
        c.varianti = varianti_leggere(*dim)
        fatto.append(f"prompt nell'ordine delle proposte; tutte a {dim[0]}×{dim[1]} come le proposte, sfondo bianco, "
                     "sguardo in camera; cambiano solo posa, angolazione, espressione e quanto si vede della figura")
        # 3) niente IPAdapter (le proposte non l'hanno) e niente ControlNet
        ip = [k for k, n in voce.workflow.items() if n.get("class_type") in ("IPAdapterAdvanced", "IPAdapter")]
        c.disattivati = sorted(set(c.disattivati) | set(ip))
        c.modifiche = {k: v for k, v in c.modifiche.items()
                       if voce.workflow.get(k, {}).get("class_type") not in NODI_IPADAPTER}
        if ip:
            fatto.append("IPAdapter staccato: con Illustrious e Pony peggiora le immagini, e le proposte non l'hanno")
        if c.pose.attive:
            c.pose.attive = False
            fatto.append("pose guidate spente")
        a.salva_config(pid, cid, c)
        app.bus.pubblica({"tipo": "dataset", "progetto": pid, "personaggio": cid, "azione": "config"})
        for x in fatto:
            l.log(f"Stessa persona · {x}", "ok")
        l.log("Pronto: genera (o «Rifai da capo»), poi «Tieni le migliori» sceglie le più somiglianti al riferimento. "
              "Con 20-30 buone addestra il LoRA: con quello il personaggio resta uguale in qualunque posa.", "ok")
        return {"fatto": fatto, "aspetto": c.aspetto}

    return app.gestore.avvia("dataset_somiglianza", f"Stessa persona per {pers.nome}, come le proposte", lavoro,
                             progetto=pid).dict()


NODI_IPADAPTER = {"IPAdapterAdvanced", "IPAdapter", "PrepImageForClipVision"}
