"""Personaggio dal nulla: proposte d'immagine di riferimento generate dal testo.

Quando un personaggio non ha ancora un'immagine, Comic Studio la crea dai suoi tratti (ricavati dall'IA dalla
descrizione libera, se serve): alcune proposte su sfondo bianco, l'utente sceglie quella giusta e diventa
l'immagine di riferimento per il dataset. Da una proposta si possono chiedere varianti (img2img).
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .projects import ErroreProgetto, Personaggio

Inquadratura = Literal["figura_intera", "mezzo_busto", "primo_piano"]

TAG_INQUADRATURA = {
    "figura_intera": "full body, standing, front view",
    "mezzo_busto": "cowboy shot, front view",
    "primo_piano": "upper body, portrait, front view",
}
DIMENSIONI = {"figura_intera": (832, 1216), "mezzo_busto": (832, 1216), "primo_piano": (1024, 1024)}
BASE = "solo, looking at viewer, neutral expression, simple background, white background"
NEGATIVO = ("{negativo_qualita}, multiple views, 2girls, 2boys, crowd, cropped, out of frame, text, watermark, "
            "signature, bad anatomy, bad hands, extra fingers, deformed, blurry, lowres")

_lock = threading.Lock()


class ConfigProposte(BaseModel):
    checkpoint: str
    numero: int = Field(4, ge=1, le=8)
    inquadratura: Inquadratura = "mezzo_busto"
    stile: str = ""                     # es. "western comics (style), cel shading"
    extra: str = ""                     # tag in più per queste proposte
    negativo: str = NEGATIVO
    passi: int = Field(28, ge=1, le=150)
    cfg: float = Field(6.0, ge=1, le=30)
    sampler: str = "euler_ancestral"
    scheduler: str = "karras"
    lora_stile: str | None = None       # una LoRA di stile installata in ComfyUI
    forza_lora: float = Field(0.8, ge=0, le=2)
    da: str | None = None               # file di una proposta: varianti di quella
    forza_variante: float = Field(0.55, ge=0.1, le=1.0)


class Ricetta(BaseModel):
    """Come è stata generata una proposta: il dataset riparte da qui (stesso checkpoint, LoRA di stile, stile,
    negativo e campionamento), così il personaggio resta lo stesso."""
    checkpoint: str
    lora_stile: str | None = None
    forza_lora: float = 0.8
    stile: str = ""
    extra: str = ""
    negativo: str | None = None         # solo se diverso da quello predefinito
    passi: int = 28
    cfg: float = 6.0
    sampler: str = "euler_ancestral"
    scheduler: str = "karras"
    inquadratura: str = "mezzo_busto"


def ricetta_da(c: ConfigProposte) -> Ricetta:
    return Ricetta(checkpoint=c.checkpoint, lora_stile=c.lora_stile or None, forza_lora=c.forza_lora,
                   stile=pulisci(c.stile), extra=pulisci(c.extra),
                   negativo=None if pulisci(c.negativo) == pulisci(NEGATIVO) else c.negativo, passi=c.passi,
                   cfg=c.cfg, sampler=c.sampler, scheduler=c.scheduler, inquadratura=c.inquadratura)


class Proposta(BaseModel):
    file: str
    seme: int
    prompt: str
    creato: float = Field(default_factory=time.time)
    da: str | None = None
    scelta: bool = False
    ricetta: Ricetta | None = None      # assente nelle proposte fatte prima della versione 0.15


def pulisci(t: str) -> str:
    return ", ".join(p.strip() for p in t.split(",") if p.strip())


def prompt_proposta(p: Personaggio, c: ConfigProposte, qualita: tuple[str, str]) -> tuple[str, str]:
    if not p.descrizione.strip():
        raise ErroreProgetto(f"{p.nome} non ha ancora i tratti: scrivi la descrizione e premi «Ricava i tratti».")
    positivo = pulisci(f"{qualita[0]}, {p.genere}, {BASE}, {p.descrizione}, {c.extra}, "
                       f"{TAG_INQUADRATURA[c.inquadratura]}, {c.stile}")
    negativo = pulisci(c.negativo.replace("{negativo_qualita}", qualita[1]))
    return positivo, negativo


def workflow(c: ConfigProposte, positivo: str, negativo: str, seme: int, immagine: str | None) -> tuple[dict, str]:
    """txt2img, oppure img2img partendo da `immagine` (già caricata in ComfyUI)."""
    w, h = DIMENSIONI[c.inquadratura]
    wf: dict = {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": c.checkpoint}}}
    modello, clip = ["1", 0], ["1", 1]
    if c.lora_stile:
        wf["10"] = {"class_type": "LoraLoader", "inputs": {"model": modello, "clip": clip, "lora_name": c.lora_stile,
                                                          "strength_model": c.forza_lora,
                                                          "strength_clip": c.forza_lora}}
        modello, clip = ["10", 0], ["10", 1]
    wf["2"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": clip, "text": positivo}}
    wf["3"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": clip, "text": negativo}}
    if immagine:
        wf["4"] = {"class_type": "LoadImage", "inputs": {"image": immagine}}
        wf["5"] = {"class_type": "ImageScale", "inputs": {"image": ["4", 0], "upscale_method": "lanczos",
                                                          "width": w, "height": h, "crop": "center"}}
        wf["6"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["5", 0], "vae": ["1", 2]}}
        latente, denoise = ["6", 0], c.forza_variante
    else:
        wf["6"] = {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}}
        latente, denoise = ["6", 0], 1.0
    wf["7"] = {"class_type": "KSampler", "inputs": {
        "model": modello, "positive": ["2", 0], "negative": ["3", 0], "latent_image": latente, "seed": seme,
        "steps": c.passi, "cfg": c.cfg, "sampler_name": c.sampler, "scheduler": c.scheduler, "denoise": denoise}}
    wf["8"] = {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["1", 2]}}
    wf["9"] = {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "comic_studio/proposte"}}
    return wf, "9"


class ArchivioProposte:
    def __init__(self, progetti):
        self.progetti = progetti

    def cartella(self, pid: str, cid: str) -> Path:
        return self.progetti.cartella_personaggio(pid, cid) / "proposte"

    def elenco(self, pid: str, cid: str) -> list[Proposta]:
        f = self.cartella(pid, cid) / "proposte.json"
        try:
            return [Proposta(**x) for x in json.loads(f.read_text(encoding="utf-8"))]
        except (OSError, ValueError):
            return []

    def _salva(self, pid: str, cid: str, elenco: list[Proposta]):
        d = self.cartella(pid, cid)
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "proposte.json.tmp"
        tmp.write_text(json.dumps([p.model_dump() for p in elenco], indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(d / "proposte.json")

    def aggiungi(self, pid: str, cid: str, dati: bytes, seme: int, prompt: str, da: str | None,
                 ricetta: Ricetta | None = None) -> Proposta:
        with _lock:
            d = self.cartella(pid, cid)
            d.mkdir(parents=True, exist_ok=True)
            elenco = self.elenco(pid, cid)
            nome = f"proposta_{len(elenco) + 1:03d}_{int(time.time() * 1000) % 100000:05d}.png"
            (d / nome).write_bytes(dati)
            p = Proposta(file=nome, seme=seme, prompt=prompt, da=da, ricetta=ricetta)
            elenco.append(p)
            self._salva(pid, cid, elenco)
            return p

    def file(self, pid: str, cid: str, nome: str) -> Path:
        if "/" in nome or "\\" in nome or not nome.endswith(".png"):
            raise ErroreProgetto("Nome di file non valido", 404)
        f = self.cartella(pid, cid) / nome
        if not f.exists():
            raise ErroreProgetto("Proposta inesistente", 404)
        return f

    def leggi(self, pid: str, cid: str, nome: str) -> Proposta | None:
        return next((p for p in self.elenco(pid, cid) if p.file == nome), None)

    def segna_scelta(self, pid: str, cid: str, nome: str):
        with _lock:
            elenco = self.elenco(pid, cid)
            for p in elenco:
                p.scelta = p.file == nome
            self._salva(pid, cid, elenco)

    def scarta(self, pid: str, cid: str) -> int:
        """Sposta nel cestino del progetto le proposte non scelte."""
        import shutil
        with _lock:
            elenco = self.elenco(pid, cid)
            restano, via = [p for p in elenco if p.scelta], [p for p in elenco if not p.scelta]
            if not via:
                return 0
            cestino = self.progetti.radice / ".cestino" / f"{pid}-{cid}-proposte-{int(time.time())}"
            cestino.mkdir(parents=True, exist_ok=True)
            for p in via:
                f = self.cartella(pid, cid) / p.file
                if f.exists():
                    shutil.move(str(f), str(cestino / p.file))
            self._salva(pid, cid, restano)
            return len(via)
