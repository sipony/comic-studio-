"""API delle trasformazioni di un personaggio (stato A → stato B): definizione, sequenza, GIF, personaggio «stato B»."""
from __future__ import annotations

import asyncio
import random

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from . import testo_prompt as tp
from .comfy.client import ComfyErrore
from .jobs import Lavoro
from .modelinfo import TAG_QUALITA, famiglia_da_nome
from .projects import ErroreProgetto, ModificaPersonaggio, NuovoPersonaggio
from .trasformazioni import (ArchivioTrasformazioni, DefinizioneTrasformazione, Fotogramma, dimensioni_da, gif,
                             negativo_b, prompt_b, valori, workflow)
from .workflows import per_invio

rotte = APIRouter(prefix="/api/progetti/{pid}/personaggi/{cid}/trasformazioni")


def _app(req: Request):
    return req.app.state.app


def _personaggio(app, pid: str, cid: str):
    p = next((c for c in app.progetti.leggi(pid).personaggi if c.id == cid), None)
    if p is None:
        raise ErroreProgetto("Personaggio inesistente", 404)
    return p


def _controlla(pers, d: DefinizioneTrasformazione):
    tp.verifica_contenuto([d.tag_b, d.togli, d.negativo_b], minori=pers.adulto is False)
    if d.fine < d.inizio:
        raise ErroreProgetto("Il denoise finale deve essere almeno quello iniziale.")


def stato_a(app, pid: str, pers, checkpoint: str | None) -> tuple[dict, str, str]:
    """(ricetta, prompt A, negativo A): quelli della proposta scelta come riferimento, parola per parola; per i
    riferimenti caricati a mano, il prompt delle proposte costruito dai tratti con il checkpoint indicato."""
    from .proposte import NEGATIVO, ArchivioProposte, ConfigProposte, Ricetta, prompt_proposta, pulisci
    ricetta = dict(pers.origine or {})
    if checkpoint:
        ricetta["checkpoint"] = checkpoint
    if not ricetta.get("checkpoint"):
        raise ErroreProgetto(f"Il riferimento di {pers.nome} non viene dalle proposte: scegli il checkpoint.")
    ricetta = Ricetta(**{k: v for k, v in ricetta.items() if k in Ricetta.model_fields}).model_dump()
    fam = famiglia_da_nome(ricetta["checkpoint"]) or "sdxl"
    q = TAG_QUALITA.get(fam, TAG_QUALITA["sdxl"])
    negativo = pulisci((ricetta.get("negativo") or NEGATIVO).replace("{negativo_qualita}", q[1]))
    scelta = next((x for x in ArchivioProposte(app.progetti).elenco(pid, pers.id) if x.scelta), None)
    if scelta:
        return ricetta, scelta.prompt, negativo
    c = ConfigProposte(checkpoint=ricetta["checkpoint"], inquadratura=ricetta["inquadratura"]
                       if ricetta["inquadratura"] in ("figura_intera", "mezzo_busto", "primo_piano") else "mezzo_busto",
                       stile=ricetta.get("stile", ""), extra=ricetta.get("extra", ""),
                       negativo=ricetta.get("negativo") or NEGATIVO, positivo=ricetta.get("positivo"))
    positivo, negativo = prompt_proposta(pers, c, q)
    return ricetta, positivo, negativo


@rotte.get("")
async def elenco(pid: str, cid: str, req: Request):
    app = _app(req)
    _personaggio(app, pid, cid)
    return [x.model_dump() for x in ArchivioTrasformazioni(app.progetti).elenco(pid, cid)]


@rotte.post("", status_code=201)
async def crea(pid: str, cid: str, d: DefinizioneTrasformazione, req: Request):
    app = _app(req)
    pers = _personaggio(app, pid, cid)
    _controlla(pers, d)
    x = ArchivioTrasformazioni(app.progetti).crea(pid, cid, d)
    app.bus.log(f"Trasformazione «{x.nome}» di {pers.nome} creata", "ok")
    return x.model_dump()


@rotte.put("/{tid}")
async def modifica(pid: str, cid: str, tid: str, d: DefinizioneTrasformazione, req: Request):
    app = _app(req)
    pers = _personaggio(app, pid, cid)
    _controlla(pers, d)
    return ArchivioTrasformazioni(app.progetti).modifica(pid, cid, tid, d).model_dump()


@rotte.delete("/{tid}")
async def elimina(pid: str, cid: str, tid: str, req: Request):
    app = _app(req)
    _personaggio(app, pid, cid)
    ArchivioTrasformazioni(app.progetti).elimina(pid, cid, tid)
    return {"ok": True}


class AnteprimaPrompt(BaseModel):
    definizione: DefinizioneTrasformazione
    checkpoint: str | None = None


@rotte.post("/anteprima")
async def anteprima(pid: str, cid: str, dati: AnteprimaPrompt, req: Request):
    """Prompt e negativo dello stato A e dello stato B, senza generare."""
    app = _app(req)
    pers = _personaggio(app, pid, cid)
    try:
        ricetta, pa, na = stato_a(app, pid, pers, dati.checkpoint)
    except ErroreProgetto as e:
        return {"errore": str(e)}
    d = dati.definizione
    return {"checkpoint": ricetta["checkpoint"], "prompt_a": pa, "negativo_a": na, "prompt_b": prompt_b(pa, d),
            "negativo_b": negativo_b(na, d), "fotogrammi": [dict(zip(("t", "denoise"), valori(d, i)))
                                                            for i in range(d.passi)]}


class Genera(BaseModel):
    seme: int | None = Field(default=None, ge=0, le=2 ** 48)
    nuovo_seme: bool = False
    checkpoint: str | None = None          # solo se il riferimento non viene dalle proposte


@rotte.post("/{tid}/genera")
async def genera(pid: str, cid: str, tid: str, dati: Genera, req: Request):
    app = _app(req)
    pers = _personaggio(app, pid, cid)
    a = ArchivioTrasformazioni(app.progetti)
    x = a.leggi(pid, cid, tid)
    _controlla(pers, x)
    if not pers.riferimento:
        raise ErroreProgetto(f"{pers.nome} non ha un'immagine di riferimento: è lo stato A da cui parte la "
                             "trasformazione.")
    if not app.comfy.connesso:
        raise ErroreProgetto("ComfyUI non è connesso: avvialo e riprova.", 409)
    ricetta, pa, na = stato_a(app, pid, pers, dati.checkpoint)
    pb, nb = prompt_b(pa, x), negativo_b(na, x)
    seme = dati.seme if dati.seme is not None else (x.seme if x.seme is not None and not dati.nuovo_seme
                                                    else random.randrange(2 ** 48))
    rif = app.progetti.file_riferimento(pid, cid)
    dimensioni = dimensioni_da(rif)

    async def lavoro(l: Lavoro):
        a.svuota_fotogrammi(pid, cid, tid)
        app.bus.pubblica({"tipo": "trasformazioni", "progetto": pid, "personaggio": cid})
        l.log(f"Trasformazione «{x.nome}» di {pers.nome}: {x.passi} fotogrammi, seme {seme}, denoise da {x.inizio} a "
              f"{x.fine}" + (f", LoRA {x.lora} fino a {x.forza_lora}" if x.lora else ""))
        l.log(f"Stato A: {pa}")
        l.log(f"Stato B: {pb}")
        async with app.client() as client:
            copia = rif.with_name(f"{pid}_{cid}_stato_a.png")
            copia.write_bytes(rif.read_bytes())
            nome = await client.carica_immagine(copia, "comic_studio_trasformazioni")
            copia.unlink(missing_ok=True)
            for i in range(x.passi):
                l.controlla()
                t, denoise = valori(x, i)
                wf = workflow(ricetta, pa, na, pb, nb, x, nome, dimensioni, t, denoise, seme)

                def avanza(v, testo, i=i):
                    l.avanza((i + v) / x.passi, f"fotogramma {i + 1}/{x.passi} · {testo}")
                l.registra_workflow(wf, {"tipo": "trasformazione", "progetto": pid, "personaggio": cid})
                uscite = await client.esegui(per_invio(wf), avanza, anteprima=l.imposta_anteprima)
                img = (uscite.get("15") or next(iter(uscite.values()), [None]))[0]
                if not img:
                    raise ComfyErrore("ComfyUI non ha restituito l'immagine.")
                dati_img = await client.scarica(img)
                l.imposta_anteprima(dati_img, "image/png", finale=True)
                f = Fotogramma(file=f"{i + 1:02d}.png", t=t, denoise=denoise, seme=seme, prompt_b=pb)
                await asyncio.to_thread(a.aggiungi_fotogramma, pid, cid, tid, dati_img, f, wf, seme)
                app.bus.pubblica({"tipo": "trasformazioni", "progetto": pid, "personaggio": cid})
                l.log(f"Fotogramma {i + 1}/{x.passi}: {round(t * 100)}% verso «{x.nome}», denoise {denoise}")
        l.log(f"Trasformazione «{x.nome}» di {pers.nome} pronta", "ok")
        return {"fotogrammi": x.passi, "seme": seme}

    return app.gestore.avvia("trasformazione", f"Trasformazione «{x.nome}» di {pers.nome}", lavoro, progetto=pid,
                             esclusivo=True).dict()


@rotte.get("/{tid}/fotogrammi/{nome}")
async def fotogramma(pid: str, cid: str, tid: str, nome: str, req: Request):
    return FileResponse(ArchivioTrasformazioni(_app(req).progetti).file(pid, cid, tid, nome),
                        headers={"Cache-Control": "no-cache"})


@rotte.get("/{tid}/fotogrammi/{nome}/workflow")
async def workflow_fotogramma(pid: str, cid: str, tid: str, nome: str, req: Request, formato: str = "grafo"):
    from .rotte_dataset import _json_scaricabile, pacchetto_grafo
    app = _app(req)
    wf = ArchivioTrasformazioni(app.progetti).workflow_di(pid, cid, tid, nome)
    if formato == "json":
        return _json_scaricabile(wf, f"comic-studio-{cid}-{tid}-{nome.removesuffix('.png')}.json")
    return await pacchetto_grafo(app, wf, f"Trasformazione {tid} · fotogramma {nome.removesuffix('.png')}", False,
                                 "immagine", f"/api/progetti/{pid}/personaggi/{cid}/trasformazioni/{tid}/fotogrammi/"
                                             f"{nome}/workflow?formato=json")


@rotte.get("/{tid}/gif")
async def scarica_gif(pid: str, cid: str, tid: str, req: Request, durata: int = 700):
    a = ArchivioTrasformazioni(_app(req).progetti)
    x = a.leggi(pid, cid, tid)
    file = [a.file(pid, cid, tid, f.file) for f in sorted(x.fotogrammi, key=lambda f: f.t)]
    dati = await asyncio.to_thread(gif, file, max(100, min(durata, 5000)))
    return Response(dati, media_type="image/gif",
                    headers={"Content-Disposition": f'attachment; filename="{cid}-{tid}.gif"'})


class NuovoDaStatoB(BaseModel):
    fotogramma: str
    nome: str | None = Field(default=None, max_length=60)


@rotte.post("/{tid}/personaggio", status_code=201)
async def personaggio_stato_b(pid: str, cid: str, tid: str, dati: NuovoDaStatoB, req: Request):
    """Un personaggio a sé per lo stato B (es. «Padre Anselmo (il mostro)»): il fotogramma scelto diventa il suo
    riferimento e la sua ricetta è quella della trasformazione con il prompt dello stato B, così il suo dataset e il suo
    LoRA ritraggono il mostro. La LoRA della trasformazione diventa la sua LoRA di stile se non ce n'è già una."""
    from .proposte import dividi_tag, nucleo
    app = _app(req)
    pers = _personaggio(app, pid, cid)
    a = ArchivioTrasformazioni(app.progetti)
    x = a.leggi(pid, cid, tid)
    f = a.file(pid, cid, tid, dati.fotogramma)
    ricetta, pa, na = stato_a(app, pid, pers, None)
    via = {nucleo(t) for t in dividi_tag(x.togli)}
    tratti = [t for t in dividi_tag(pers.descrizione) if nucleo(t) not in via] + dividi_tag(x.tag_b)
    nuovo = app.progetti.aggiungi_personaggio(pid, NuovoPersonaggio(
        nome=(dati.nome or f"{pers.nome} ({x.nome})")[:60], genere=pers.genere,
        descrizione=", ".join(tratti)[:1500]))
    origine = {**ricetta, "positivo": prompt_b(pa, x), "negativo": negativo_b(na, x)}
    avviso = None
    if x.lora:
        if not ricetta.get("lora_stile"):
            origine |= {"lora_stile": x.lora, "forza_lora": x.forza_lora}
        else:
            avviso = (f"La LoRA della trasformazione ({x.lora}) non è nella ricetta di «{nuovo.nome}», che ha già la LoRA "
                      f"di stile {ricetta['lora_stile']}: il riferimento la mostra, il dataset no (il LoRA del "
                      "personaggio la imparerà dalle immagini).")
    if pers.adulto is not None:
        app.progetti.modifica_personaggio(pid, nuovo.id, ModificaPersonaggio(adulto=pers.adulto))
    nuovo = app.progetti.salva_riferimento(pid, nuovo.id, await asyncio.to_thread(f.read_bytes), origine)
    try:                                   # il suo dataset nasce come le «proposte» dello stato B
        from .rotte_dataset import prepara_come_proposte
        await prepara_come_proposte(app, pid, nuovo.id, origine)
    except Exception as e:  # noqa: BLE001 - il personaggio c'è comunque
        app.bus.log(f"Dataset di «{nuovo.nome}» da preparare a mano: {e}", "avviso")
    app.bus.pubblica({"tipo": "personaggi", "progetto": pid, "personaggio": nuovo.id})
    app.bus.log(f"Nuovo personaggio «{nuovo.nome}» dallo stato B di «{x.nome}»", "ok")
    if avviso:
        app.bus.log(avviso, "avviso")
    return {"personaggio": nuovo.model_dump(), "avviso": avviso}
