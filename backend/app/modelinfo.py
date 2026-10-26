"""Informazioni sui file dei modelli senza caricarli: dimensione, precisione, architettura.

Legge solo l'intestazione dei file .safetensors (pochi KB), quindi è veloce anche su modelli da 7 GB.
"""
from __future__ import annotations

import json
import re
import struct
from dataclasses import asdict, dataclass
from pathlib import Path

GB = 1024 ** 3

# famiglia -> tag di qualità consigliati per i prompt
TAG_QUALITA = {
    "pony": ("score_9, score_8_up, score_7_up", "score_4, score_5, score_6"),
    "illustrious": ("masterpiece, best quality, amazing quality", "worst quality, low quality, bad quality"),
    "noobai": ("masterpiece, best quality, newest, absurdres", "worst quality, low quality, old, early"),
    "sdxl": ("high quality, detailed", "low quality, blurry"),
    "sd15": ("masterpiece, best quality", "worst quality, low quality"),
    "flux": ("", ""),
}


@dataclass
class InfoModello:
    file: str
    dimensione: int
    formato: str                 # safetensors, gguf, ckpt...
    famiglia: str | None = None  # pony, illustrious, noobai, sdxl, sd15, flux, sd3...
    precisione: str | None = None  # fp32, fp16, bf16, fp8, q4_k_s...
    quantizzato: bool = False
    metadati: dict | None = None

    def dict(self):
        d = asdict(self)
        d["dimensione_gb"] = round(self.dimensione / GB, 2)
        return d


def leggi_intestazione(f: Path) -> dict | None:
    try:
        with open(f, "rb") as h:
            n = struct.unpack("<Q", h.read(8))[0]
            if n <= 0 or n > 100 * 1024 * 1024:
                return None
            return json.loads(h.read(n))
    except (OSError, struct.error, ValueError, UnicodeDecodeError):
        return None


def famiglia_da_nome(nome: str) -> str | None:
    n = nome.lower()
    regole = [
        (r"pony|pdxl|autismmix|ponyrealism", "pony"),
        (r"noob", "noobai"),
        (r"illustrious|ilxl|waiillustrious|wai-?nsfw-illustrious|hassaku.*xl", "illustrious"),
        (r"flux|schnell", "flux"),
        (r"sd3|sd_3", "sd3"),
        (r"xl|sdxl", "sdxl"),
        (r"sd15|sd-1|v1-5|1\.5", "sd15"),
    ]
    for regex, fam in regole:
        if re.search(regex, n):
            return fam
    return None


def famiglia_da_metadati(meta: dict) -> str | None:
    testo = " ".join(str(meta.get(k, "")) for k in
                     ("modelspec.architecture", "ss_base_model_version", "modelspec.title",
                      "ss_sd_model_name", "modelspec.description")).lower()
    if not testo.strip():
        return None
    if "pony" in testo:
        return "pony"
    if "noob" in testo:
        return "noobai"
    if "illustrious" in testo:
        return "illustrious"
    if "flux" in testo:
        return "flux"
    if "stable-diffusion-v3" in testo or "sd3" in testo:
        return "sd3"
    if "xl" in testo:
        return "sdxl"
    if "v1" in testo or "sd_v1" in testo:
        return "sd15"
    return None


def precisione_da_tensori(intest: dict) -> str | None:
    conteggio: dict[str, int] = {}
    for k, v in intest.items():
        if k == "__metadata__" or not isinstance(v, dict):
            continue
        dt = v.get("dtype")
        if dt:
            conteggio[dt] = conteggio.get(dt, 0) + 1
    if not conteggio:
        return None
    dominante = max(conteggio, key=conteggio.get)
    return {"F32": "fp32", "F16": "fp16", "BF16": "bf16", "F8_E4M3": "fp8", "F8_E5M2": "fp8"}.get(dominante,
                                                                                                 dominante.lower())


def analizza(f: Path) -> InfoModello:
    est = f.suffix.lower().lstrip(".")
    info = InfoModello(file=f.name, dimensione=f.stat().st_size, formato=est)
    if est == "gguf":
        info.quantizzato = True
        m = re.search(r"(q\d(_k)?(_[sml])?|q8_0|f16|bf16)", f.name.lower())
        info.precisione = m.group(1) if m else "gguf"
    elif est == "safetensors":
        intest = leggi_intestazione(f)
        if intest:
            meta = intest.get("__metadata__") or {}
            info.metadati = {k: v for k, v in meta.items() if len(str(v)) < 300} or None
            info.precisione = precisione_da_tensori(intest)
            info.quantizzato = info.precisione == "fp8"
            info.famiglia = famiglia_da_metadati(meta)
    info.famiglia = info.famiglia or famiglia_da_nome(f.name)
    return info


# ---------------------------------------------------------------- ControlNet: per SD 1.5 o per SDXL?

# file di ControlNet / T2I-Adapter per SD 1.5 riconoscibili dal nome (es. control_v11p_sd15_openpose.pth)
NOME_SD15 = re.compile(r"sd-?_?1[45]|v11[pfe]|control_sd|_sd14|1\.5", re.I)
NOME_SDXL = re.compile(r"xl|sdxl|pony|illustrious|noob", re.I)
# dimensione del contesto dei prompt (cross-attention) → architettura
CONTESTO = {768: "sd15", 1024: "sd2", 2048: "sdxl", 4096: "flux"}


def architettura_controlnet(nome: str, file: Path | None = None) -> str | None:
    """«sd15», «sdxl», «sd2»… Dal file (.safetensors: la forma di un peso di cross-attention, senza caricarlo) se c'è,
    altrimenti dal nome. None se non si capisce."""
    if file is not None and file.suffix.lower() == ".safetensors" and file.is_file():
        intest = leggi_intestazione(file) or {}
        for k, v in intest.items():
            if isinstance(v, dict) and k.endswith(("attn2.to_k.weight", "attn2.k_proj.weight")) \
                    and len(v.get("shape") or []) == 2:
                arch = CONTESTO.get(int(v["shape"][1]))
                if arch:
                    return arch
    base = Path(nome).name
    if NOME_SDXL.search(base):
        return "sdxl"
    if NOME_SD15.search(base):
        return "sd15"
    return None


def architettura_checkpoint(nome: str) -> str:
    """L'architettura per cui serve il ControlNet: le famiglie SDXL (Pony, Illustrious, NoobAI) sono «sdxl»."""
    fam = famiglia_da_nome(nome or "") or "sdxl"
    return {"pony": "sdxl", "illustrious": "sdxl", "noobai": "sdxl"}.get(fam, fam)


def consiglio_spazio(info: InfoModello) -> str | None:
    """Suggerisce come risparmiare spazio e memoria con lo stesso modello."""
    gb = info.dimensione / GB
    if info.famiglia in ("sdxl", "pony", "illustrious", "noobai") and info.precisione == "fp32" and gb > 9:
        return f"{info.file} è in fp32 ({gb:.1f} GB): la versione fp16 pesa circa la metà con la stessa qualità."
    if info.famiglia == "flux" and info.precisione in ("fp16", "bf16", "fp32") and gb > 20:
        return (f"{info.file} è Flux a precisione piena ({gb:.1f} GB): con poca VRAM usa una versione "
                "GGUF Q4_K_S/Q5_K_S o fp8 (circa 7-12 GB).")
    return None
