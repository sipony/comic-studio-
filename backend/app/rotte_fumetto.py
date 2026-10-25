"""API e lavori dello Step 4 (Fumetto)."""
from __future__ import annotations

import asyncio
import io
import random
import time
import zipfile

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from PIL import Image, ImageOps
from pydantic import BaseModel

from . import fumetto as fm
from .addestramento import ArchivioAddestramento
from .comfy.client import ComfyErrore
from .jobs import Lavoro
from .llm import ErroreIA
from .modelinfo import TAG_QUALITA, famiglia_da_nome
from .projects import slug
from .workflows import per_invio

rotte = APIRouter(prefix="/api/progetti/{pid}/fumetto")


def _app(req: Request):
    return req.app.state.app


def _arch(req: Request) -> fm.ArchivioFumetto:
    return fm.ArchivioFumetto(_app(req).progetti)


def _lora(req: Request, pid: str) -> dict[str, str | None]:
    a = ArchivioAddestramento(_app(req).progetti)
    return {c.id: a.stato(pid, c.id).lora_finale for c in _app(req).progetti.leggi(pid).personaggi}


def _qualita(imp: fm.Impostazioni) -> tuple[str, str]:
    pos, neg = TAG_QUALITA.get(famiglia_da_nome(imp.checkpoint or "") or "sdxl", TAG_QUALITA["sdxl"])
    return (imp.tag_qualita if imp.tag_qualita is not None else pos,
            imp.tag_qualita_negativi if imp.tag_qualita_negativi is not None else neg)


def _stato(req: Request, pid: str) -> dict:
    f = _arch(req).leggi(pid)
    imm = _arch(req).immagini(pid)
    return {"fumetto": f.model_dump(), "immagini": {k: v.model_dump() for k, v in imm.items()},
            "lora": _lora(req, pid)}


@rotte.get("")
async def stato(pid: str, req: Request):
    return await asyncio.to_thread(_stato, req, pid)


@rotte.put("")
async def salva(pid: str, f: fm.Fumetto, req: Request):
    ids = {c.id for c in _app(req).progetti.leggi(pid).personaggi}
    for p in f.pagine:
        for v in p.vignette:
            ignoti = [x for x in v.personaggi if x not in ids]
            if ignoti:
                raise HTTPException(400, f"Personaggi inesistenti nella vignetta: {', '.join(ignoti)}")
            for d in v.dialoghi:
                if d.chi != "narratore" and d.chi not in ids:
                    d.chi = "narratore"
    # l'interfaccia non rimanda l'analisi dell'IA: si tiene quella salvata (vale finché il testo non cambia)
    vecchio = {v.id: v for p in _arch(req).leggi(pid).pagine for v in p.vignette}
    for p in f.pagine:
        for v in p.vignette:
            prima = vecchio.get(v.id)
            if v.analisi is None and prima and prima.analisi:
                v.analisi = prima.analisi
    _arch(req).salva(pid, f)
    return {"ok": True}


class Importa(BaseModel):
    testo: str
    sostituisci: bool = False


@rotte.post("/importa")
async def importa(pid: str, dati: Importa, req: Request):
    a = _arch(req)
    nuove = fm.importa_storia(dati.testo, _app(req).progetti.leggi(pid).personaggi)
    f = a.leggi(pid)
    vuoto = all(not p.vignette for p in f.pagine)
    f.pagine = nuove if (dati.sostituisci or vuoto) else f.pagine + nuove
    a.salva(pid, f)
    n = sum(len(p.vignette) for p in nuove)
    _app(req).bus.log(f"Importate {len(nuove)} pagine con {n} vignette", "ok")
    return await asyncio.to_thread(_stato, req, pid)


class SceltaVersione(BaseModel):
    indice: int


@rotte.put("/vignette/{vid}/scelta")
async def scelta(pid: str, vid: str, dati: SceltaVersione, req: Request):
    return _arch(req).scegli_versione(pid, vid, dati.indice).model_dump()


@rotte.get("/immagini/{nome}")
async def immagine(pid: str, nome: str, req: Request):
    return FileResponse(_arch(req).file(pid, nome), headers={"Cache-Control": "max-age=86400"})


# ---------------------------------------------------------------- generazione

class Genera(BaseModel):
    vignette: list[str] | None = None     # None = tutte quelle senza immagine
    stesso_seme: bool = False


@rotte.post("/genera")
async def genera(pid: str, dati: Genera, req: Request):
    app = _app(req)
    a = _arch(req)
    f = a.leggi(pid)
    if not f.impostazioni.checkpoint:
        raise HTTPException(400, "Scegli il checkpoint del fumetto nelle impostazioni.")
    if not app.comfy.connesso:
        raise HTTPException(409, "ComfyUI non è connesso: avvialo e riprova.")
    imm = a.immagini(pid)
    tutte = [v for p in f.pagine for v in p.vignette]
    if dati.vignette is None:
        da_fare = [v for v in tutte if not (imm.get(v.id) and imm[v.id].versioni)]
    else:
        da_fare = [v for v in tutte if v.id in set(dati.vignette)]
    if not da_fare:
        raise HTTPException(400, "Nessuna vignetta da generare.")
    personaggi = {c.id: c for c in app.progetti.leggi(pid).personaggi}
    lora = _lora(req, pid)
    numeri = {v.id: i + 1 for i, v in enumerate(tutte)}

    async def lavoro(l: Lavoro):
        from .rotte_testo import analizza
        # 1. le descrizioni in linguaggio naturale diventano prompt (prima, così l'IA e ComfyUI non si
        #    contendono la GPU)
        scene: dict[str, object] = {}
        con_testo = [v for v in da_fare if v.descrizione.strip()]
        for k, v in enumerate(con_testo):
            l.controlla()
            l.avanza(0.15 * k / len(con_testo), f"l'IA legge la vignetta {numeri[v.id]}")
            try:
                r = await analizza(app, pid, v.id, l)
            except ErroreIA as e:
                if not v.azione.strip():
                    raise ErroreIA(f"Vignetta {numeri[v.id]}: {e} Senza IA serve almeno il campo «tag» della "
                                   "vignetta, in inglese.", non_pronta=e.codice == "ia_non_pronta") from None
                l.log(f"Vignetta {numeri[v.id]}: {e} Uso solo i tag della vignetta.", "avviso")
                continue
            if r:
                scene[v.id] = r[1]
        f2 = a.leggi(pid)                     # personaggi eventualmente trovati dall'IA
        aggiornate = {x.id: x for p in f2.pagine for x in p.vignette}
        da_fare[:] = [aggiornate.get(v.id, v) for v in da_fare]
        quota = 0.15 if con_testo else 0.0
        tagger = None
        if scene:
            try:
                from .didascalie import carica_tagger
                from .settings import cartella_dati
                tagger = await asyncio.to_thread(carica_tagger, cartella_dati() / "modelli", "wd-vit-tagger-v3",
                                                 None, l.log)
            except Exception as e:  # noqa: BLE001 - l'aderenza è un di più
                l.log(f"Controllo di aderenza non disponibile: {e}", "avviso")
        senza = {p for v in da_fare for p in v.personaggi if not lora.get(p)}
        for p in senza:
            l.log(f"{personaggi[p].nome} non ha ancora un LoRA (Step 3): uso solo la sua descrizione, sarà meno "
                  "coerente.", "avviso")
        inizio = time.time()
        async with app.client() as client:
            for k, v in enumerate(da_fare):
                l.controlla()
                precedenti = a.immagini(pid).get(v.id)
                corrente = precedenti.corrente() if precedenti else None
                # stesso seme = stessa scena con le modifiche fatte; altrimenti il seme fissato a mano o uno nuovo
                if dati.stesso_seme and corrente:
                    seme = corrente.seme
                else:
                    seme = v.seme if v.seme is not None else random.randrange(2 ** 48)
                pers = [personaggi[x] for x in v.personaggi if x in personaggi]
                scena = scene.get(v.id)
                wf, salva_id, prompt = fm.Costruttore(f.impostazioni, _qualita(f.impostazioni)).costruisci(
                    v, pers, lora, seme, scena)
                chi = " + ".join(p.nome for p in pers) or "scena"
                l.log(f"Vignetta {numeri[v.id]} ({chi}): {prompt}" if scena else
                      f"Vignetta {numeri[v.id]} ({chi}): {v.azione}")

                def avanza(x, t, k=k):
                    l.avanza(quota + (1 - quota) * (k + x) / len(da_fare), f"vignetta {k + 1}/{len(da_fare)} · {t}")
                uscite = await client.esegui(per_invio(wf), avanza, anteprima=l.imposta_anteprima)
                img = (uscite.get(salva_id) or next(iter(uscite.values()), [None]))[0]
                if not img:
                    raise ComfyErrore("ComfyUI non ha restituito l'immagine della vignetta.")
                dati_img = await client.scarica(img)
                l.imposta_anteprima(dati_img, "image/png", finale=True)
                iv = await asyncio.to_thread(a.aggiungi_versione, pid, v.id, dati_img, seme, prompt)
                if tagger and scena and scena.chiave:
                    await asyncio.to_thread(_aderenza, a, pid, v.id, iv, tagger, scena.chiave, l, numeri[v.id])
                app.bus.pubblica({"tipo": "fumetto", "progetto": pid, "vignetta": v.id})
        l.log(f"Generate {len(da_fare)} vignette in {int(time.time() - inizio)} s", "ok")
        return {"generate": len(da_fare)}

    titolo = f"Fumetto: {len(da_fare)} vignett{'a' if len(da_fare) == 1 else 'e'}"
    return app.gestore.avvia("fumetto_genera", titolo, lavoro, progetto=pid, esclusivo=True).dict()


def _aderenza(a: fm.ArchivioFumetto, pid: str, vid: str, iv: fm.ImmaginiVignetta, tagger, chiave: list[str],
              l: Lavoro, numero: int):
    from .testo_prompt import aderenza
    ultima = iv.versioni[-1]
    tag = tagger.tagga([a.file(pid, ultima.file)])
    r = aderenza(next(iter(tag.values()), {}), chiave, set(tagger.nomi))
    a.imposta_aderenza(pid, vid, len(iv.versioni) - 1, r)
    if r["punteggio"] is not None:
        testo = f"Vignetta {numero}: aderenza {len(r['trovati'])}/{len(r['trovati']) + len(r['mancanti'])}"
        if r["mancanti"]:
            testo += " — mancano: " + ", ".join(r["mancanti"])
        l.log(testo, "ok" if not r["mancanti"] else "avviso")


# ---------------------------------------------------------------- tavole

def _immagine_di(a: fm.ArchivioFumetto, pid: str, f: fm.Fumetto, nomi: dict[str, str]):
    imm = a.immagini(pid)

    def di(v: fm.Vignetta) -> Image.Image:
        iv = imm.get(v.id)
        c = iv.corrente() if iv else None
        if c:
            # stessa proporzione della vignetta: i balloon hanno sempre la scala giusta
            base = ImageOps.fit(Image.open(a.file(pid, c.file)).convert("RGB"), fm.DIMENSIONI[v.formato], Image.LANCZOS)
        else:
            base = fm.segnaposto(v, nomi)
        return fm.disegna_balloon(base, v, f.impostazioni.font)
    return di


def _pagine(req: Request, pid: str) -> list[Image.Image]:
    a = _arch(req)
    f = a.leggi(pid)
    nomi = {c.id: c.nome for c in _app(req).progetti.leggi(pid).personaggi}
    di = _immagine_di(a, pid, f, nomi)
    return [fm.componi_pagina(p, di, f.impostazioni) for p in f.pagine if p.vignette]


@rotte.get("/pagine/{indice}/anteprima")
async def anteprima(pid: str, indice: int, req: Request, larghezza: int = 900):
    def fai():
        a = _arch(req)
        f = a.leggi(pid)
        if not 0 <= indice < len(f.pagine) or not f.pagine[indice].vignette:
            raise HTTPException(404, "Pagina vuota o inesistente")
        nomi = {c.id: c.nome for c in _app(req).progetti.leggi(pid).personaggi}
        img = fm.componi_pagina(f.pagine[indice], _immagine_di(a, pid, f, nomi), f.impostazioni)
        if larghezza and larghezza < img.width:
            img = img.resize((larghezza, round(img.height * larghezza / img.width)), Image.LANCZOS)
        b = io.BytesIO()
        img.save(b, "JPEG", quality=88)
        return b.getvalue()
    return Response(await asyncio.to_thread(fai), media_type="image/jpeg", headers={"Cache-Control": "no-cache"})


@rotte.get("/esporta")
async def esporta(pid: str, req: Request, formato: str = "pdf"):
    pagine = await asyncio.to_thread(_pagine, req, pid)
    if not pagine:
        raise HTTPException(400, "Il fumetto non ha ancora vignette.")
    nome = slug(_app(req).progetti.leggi(pid).nome)
    if formato == "pdf":
        dati = await asyncio.to_thread(fm.pdf, pagine)
        return Response(dati, media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{nome}.pdf"'})

    def fai_zip():
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w", zipfile.ZIP_STORED) as z:
            for i, p in enumerate(pagine, 1):
                pb = io.BytesIO()
                p.save(pb, "PNG")
                z.writestr(f"{nome}_pagina_{i:02d}.png", pb.getvalue())
        return b.getvalue()
    return Response(await asyncio.to_thread(fai_zip), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{nome}_tavole.zip"'})
