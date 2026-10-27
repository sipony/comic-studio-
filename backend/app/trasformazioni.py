"""Trasformazioni di un personaggio: da uno stato A (com'è) a uno stato B (es. il prete che diventa mostro).

La trasformazione si definisce una volta nella scheda del personaggio (tag dello stato B, tag di A da togliere,
negativo in più, LoRA della trasformazione) e si genera come sequenza di fotogrammi dall'immagine di riferimento:
  - stesso seme e stessa immagine di partenza per tutti i fotogrammi (stessa inquadratura, stessa persona)
  - il prompt scivola da A a B: ConditioningAverage(B, A, t), con t da 0 a 1
  - la LoRA della trasformazione sale da 0 alla sua forza (forza × t)
  - il denoise sale da «inizio» a «fine»: all'inizio resta il riferimento, alla fine c'è spazio per il cambiamento
Il contenuto dello stato B (body horror, gore o niente) lo decidono solo i tag e la LoRA scelti dall'utente: vivono
solo nella trasformazione, il dataset e le immagini normali del personaggio non li vedono.

File:  <personaggio>/trasformazioni/trasformazioni.json          definizioni e fotogrammi
       <personaggio>/trasformazioni/<id>/01.png …                fotogrammi
       <personaggio>/trasformazioni/<id>/workflow/01.json …      workflow mandati a ComfyUI
"""
from __future__ import annotations

import io
import json
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

from PIL import Image
from pydantic import BaseModel, Field

from .projects import ErroreProgetto, slug

_lock = threading.RLock()


class DefinizioneTrasformazione(BaseModel):
    nome: str = Field(min_length=1, max_length=60)               # es. «Il mostro»
    tag_b: str = Field(min_length=1, max_length=3000)              # come diventa (in inglese, a tag)
    togli: str = Field(default="", max_length=1500)                # tag di A che nello stato B non valgono più
    negativo_b: str = Field(default="", max_length=1500)           # negativo in più per lo stato B
    lora: str | None = None                                        # LoRA della trasformazione (facoltativa)
    forza_lora: float = Field(default=0.8, ge=0, le=2)
    passi: int = Field(default=5, ge=2, le=12)                     # fotogrammi da A a B
    inizio: float = Field(default=0.3, ge=0.05, le=1)              # denoise del primo fotogramma
    fine: float = Field(default=0.85, ge=0.05, le=1)               # denoise dell'ultimo


class Fotogramma(BaseModel):
    file: str
    t: float                                                       # 0 = stato A, 1 = stato B
    denoise: float
    seme: int
    prompt_b: str = ""


class Trasformazione(DefinizioneTrasformazione):
    id: str
    creato: float = Field(default_factory=time.time)
    fotogrammi: list[Fotogramma] = Field(default_factory=list)
    seme: int | None = None


def tag(testo: str) -> list[str]:
    from .proposte import dividi_tag
    return dividi_tag(testo or "")


def prompt_b(prompt_a: str, d: DefinizioneTrasformazione) -> str:
    """Il prompt dello stato B: quello di A senza i tag da togliere, con i tag di B prima dello stile (in fondo se non
    si sa dov'è lo stile)."""
    from .proposte import nucleo
    via = {nucleo(t) for t in tag(d.togli)}
    resto = [t for t in tag(prompt_a) if nucleo(t) not in via]
    return ", ".join(resto + tag(d.tag_b))


def negativo_b(negativo_a: str, d: DefinizioneTrasformazione) -> str:
    return ", ".join(tag(negativo_a) + tag(d.negativo_b))


def valori(d: DefinizioneTrasformazione, i: int) -> tuple[float, float]:
    """(t, denoise) del fotogramma i."""
    t = i / (d.passi - 1)
    return round(t, 4), round(d.inizio + (d.fine - d.inizio) * t, 4)


def workflow(ricetta: dict, pos_a: str, neg_a: str, pos_b: str, neg_b: str, d: DefinizioneTrasformazione,
             immagine: str, dimensioni: tuple[int, int], t: float, denoise: float, seme: int) -> dict:
    """img2img dal riferimento con il prompt che va da A a B e la LoRA della trasformazione che sale."""
    w, h = dimensioni
    wf: dict = {}

    def nodo(k, classe, titolo, **ing):
        wf[k] = {"class_type": classe, "inputs": ing, "_meta": {"title": titolo}}

    nodo("1", "CheckpointLoaderSimple", "Checkpoint", ckpt_name=ricetta["checkpoint"])
    modello, clip = ["1", 0], ["1", 1]
    if ricetta.get("lora_stile"):
        f = ricetta.get("forza_lora", 0.8)
        nodo("2", "LoraLoader", "LoRA di stile", model=modello, clip=clip, lora_name=ricetta["lora_stile"],
             strength_model=f, strength_clip=f)
        modello, clip = ["2", 0], ["2", 1]
    if d.lora:
        f = round(d.forza_lora * t, 4)
        nodo("3", "LoraLoader", "LoRA della trasformazione", model=modello, clip=clip, lora_name=d.lora,
             strength_model=f, strength_clip=f)
        modello, clip = ["3", 0], ["3", 1]
    nodo("4", "CLIPTextEncode", "Prompt A", clip=clip, text=pos_a)
    nodo("5", "CLIPTextEncode", "Negativo A", clip=clip, text=neg_a)
    nodo("6", "CLIPTextEncode", "Prompt B", clip=clip, text=pos_b)
    nodo("7", "CLIPTextEncode", "Negativo B", clip=clip, text=neg_b)
    nodo("8", "ConditioningAverage", "Da A a B", conditioning_to=["6", 0], conditioning_from=["4", 0],
         conditioning_to_strength=t)
    nodo("9", "ConditioningAverage", "Negativo da A a B", conditioning_to=["7", 0], conditioning_from=["5", 0],
         conditioning_to_strength=t)
    nodo("10", "LoadImage", "Riferimento (stato A)", image=immagine)
    nodo("11", "ImageScale", "Dimensioni", image=["10", 0], upscale_method="lanczos", width=w, height=h,
         crop="center")
    nodo("12", "VAEEncode", "Codifica", pixels=["11", 0], vae=["1", 2])
    nodo("13", "KSampler", "Sampler", model=modello, positive=["8", 0], negative=["9", 0], latent_image=["12", 0],
         seed=seme, steps=ricetta.get("passi", 28), cfg=ricetta.get("cfg", 6.0),
         sampler_name=ricetta.get("sampler", "euler_ancestral"), scheduler=ricetta.get("scheduler", "karras"),
         denoise=denoise)
    nodo("14", "VAEDecode", "Decodifica", samples=["13", 0], vae=["1", 2])
    nodo("15", "SaveImage", "Salva", images=["14", 0], filename_prefix="comic_studio/trasformazioni")
    return wf


def dimensioni_da(file: Path) -> tuple[int, int]:
    """Le dimensioni SDXL più vicine alla forma del riferimento."""
    with Image.open(file) as img:
        r = img.width / max(1, img.height)
    if r < 0.85:
        return 832, 1216
    if r > 1.18:
        return 1216, 832
    return 1024, 1024


def gif(fotogrammi: list[Path], durata_ms: int = 700, lato: int = 512) -> bytes:
    """GIF animata della sequenza, avanti e indietro (A → B → A), con una pausa sugli estremi."""
    immagini = []
    for f in fotogrammi:
        with Image.open(f) as img:
            img = img.convert("RGB")
            img.thumbnail((lato, lato), Image.LANCZOS)
            immagini.append(img.copy())
    if not immagini:
        raise ErroreProgetto("Nessun fotogramma: genera prima la trasformazione.", 404)
    giro = immagini + immagini[-2:0:-1]
    durate = [durata_ms * (3 if i in (0, len(immagini) - 1) else 1) for i in range(len(giro))]
    buf = io.BytesIO()
    giro[0].save(buf, "GIF", save_all=True, append_images=giro[1:], duration=durate, loop=0, optimize=True)
    return buf.getvalue()


class ArchivioTrasformazioni:
    def __init__(self, progetti):
        self.progetti = progetti

    def cartella(self, pid: str, cid: str) -> Path:
        return self.progetti.cartella_personaggio(pid, cid) / "trasformazioni"

    def elenco(self, pid: str, cid: str) -> list[Trasformazione]:
        f = self.cartella(pid, cid) / "trasformazioni.json"
        try:
            return [Trasformazione(**x) for x in json.loads(f.read_text(encoding="utf-8"))]
        except (OSError, ValueError):
            return []

    def _salva(self, pid: str, cid: str, elenco: list[Trasformazione]):
        d = self.cartella(pid, cid)
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "trasformazioni.json.tmp"
        tmp.write_text(json.dumps([x.model_dump() for x in elenco], indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(d / "trasformazioni.json")

    def leggi(self, pid: str, cid: str, tid: str) -> Trasformazione:
        x = next((x for x in self.elenco(pid, cid) if x.id == tid), None)
        if x is None:
            raise ErroreProgetto("Trasformazione inesistente", 404)
        return x

    def crea(self, pid: str, cid: str, d: DefinizioneTrasformazione) -> Trasformazione:
        with _lock:
            elenco = self.elenco(pid, cid)
            tid = f"{slug(d.nome)[:30] or 'trasformazione'}-{uuid.uuid4().hex[:5]}"
            x = Trasformazione(id=tid, **d.model_dump())
            self._salva(pid, cid, elenco + [x])
            return x

    def modifica(self, pid: str, cid: str, tid: str, d: DefinizioneTrasformazione) -> Trasformazione:
        with _lock:
            elenco = self.elenco(pid, cid)
            for i, x in enumerate(elenco):
                if x.id == tid:
                    elenco[i] = Trasformazione(**{**x.model_dump(), **d.model_dump()})
                    self._salva(pid, cid, elenco)
                    return elenco[i]
        raise ErroreProgetto("Trasformazione inesistente", 404)

    def _nel_cestino(self, pid: str, cid: str, sorgente: Path, nome: str):
        if sorgente.exists():
            cestino = self.progetti.radice / ".cestino"
            cestino.mkdir(parents=True, exist_ok=True)
            shutil.move(str(sorgente), str(cestino / f"{pid}-{cid}-{nome}-{int(time.time())}"))

    def elimina(self, pid: str, cid: str, tid: str):
        with _lock:
            elenco = self.elenco(pid, cid)
            x = next((x for x in elenco if x.id == tid), None)
            if x is None:
                raise ErroreProgetto("Trasformazione inesistente", 404)
            self._nel_cestino(pid, cid, self.cartella(pid, cid) / tid, f"trasformazione-{tid}")
            self._salva(pid, cid, [y for y in elenco if y.id != tid])

    def svuota_fotogrammi(self, pid: str, cid: str, tid: str):
        """Prima di una nuova sequenza: la vecchia va nel cestino."""
        with _lock:
            elenco = self.elenco(pid, cid)
            for x in elenco:
                if x.id == tid:
                    self._nel_cestino(pid, cid, self.cartella(pid, cid) / tid, f"trasformazione-{tid}")
                    x.fotogrammi = []
            self._salva(pid, cid, elenco)

    def aggiungi_fotogramma(self, pid: str, cid: str, tid: str, dati: bytes, f: Fotogramma, wf: dict, seme: int):
        with _lock:
            d = self.cartella(pid, cid) / tid
            (d / "workflow").mkdir(parents=True, exist_ok=True)
            (d / f.file).write_bytes(dati)
            (d / "workflow" / (Path(f.file).stem + ".json")).write_text(json.dumps(wf, ensure_ascii=False),
                                                                        encoding="utf-8")
            elenco = self.elenco(pid, cid)
            for x in elenco:
                if x.id == tid:
                    x.fotogrammi = [y for y in x.fotogrammi if y.file != f.file] + [f]
                    x.seme = seme
            self._salva(pid, cid, elenco)

    def file(self, pid: str, cid: str, tid: str, nome: str) -> Path:
        if not re.fullmatch(r"[\w-]{1,64}", tid) or not re.fullmatch(r"\d{2}\.png", nome):
            raise ErroreProgetto("Nome di file non valido", 404)
        f = self.cartella(pid, cid) / tid / nome
        if not f.is_file():
            raise ErroreProgetto("Fotogramma inesistente", 404)
        return f

    def workflow_di(self, pid: str, cid: str, tid: str, nome: str) -> dict:
        self.file(pid, cid, tid, nome)
        f = self.cartella(pid, cid) / tid / "workflow" / (Path(nome).stem + ".json")
        if not f.is_file():
            raise ErroreProgetto("Workflow del fotogramma non trovato", 404)
        return json.loads(f.read_text(encoding="utf-8"))


__all__ = ["ArchivioTrasformazioni", "DefinizioneTrasformazione", "Fotogramma", "Trasformazione", "gif",
           "negativo_b", "prompt_b", "valori", "workflow"]
