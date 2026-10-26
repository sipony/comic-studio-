"""Componenti di ComfyUI che servono a Comic Studio e che si possono installare da qui: IPAdapter Plus.

Senza IPAdapter il dataset nasce solo dal testo e i volti cambiano da un'immagine all'altra. Servono tre cose:
  - il custom node ComfyUI_IPAdapter_plus      → <ComfyUI>/custom_nodes/ComfyUI_IPAdapter_plus
  - il modello ip-adapter-plus_sdxl_vit-h       → <ComfyUI>/models/ipadapter
  - CLIP Vision ViT-H (rinominato come vuole il nodo) → <ComfyUI>/models/clip_vision

All'apertura Comic Studio controlla se mancano e l'interfaccia chiede se installarli, dicendo quanto spazio serve e
quanto ce n'è (sul disco di ComfyUI). I file si scaricano in <nome>.parziale e diventano definitivi solo se la
dimensione (e l'impronta SHA-256, quando Hugging Face la dà) è giusta. Il nodo si carica solo riavviando ComfyUI.
"""
from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import subprocess
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import httpx

GB = 1024 ** 3
MARGINE = 1 * GB                     # spazio da lasciare libero oltre a quello dei file


@dataclass
class Componente:
    id: str
    nome: str
    tipo: str                        # nodo, modello
    descrizione: str
    cartella: str                    # relativa alla cartella di ComfyUI
    file: str                        # nome della cartella (nodo) o del file (modello)
    url: str
    byte: int                        # dimensione attesa (stima, aggiornata dal server quando si scarica)
    riconosci: str                   # regex sul nome: c'è già (anche con un altro nome)
    nodo: str | None = None          # per i nodi: un tipo di nodo che dimostra che è caricato
    git: str | None = None           # per i nodi: repository da clonare (se c'è git)


IPADAPTER = [
    Componente("nodo_ipadapter", "ComfyUI_IPAdapter_plus", "nodo",
               "il custom node che fa somigliare le immagini al riferimento",
               "custom_nodes", "ComfyUI_IPAdapter_plus",
               "https://github.com/cubiq/ComfyUI_IPAdapter_plus/archive/refs/heads/main.zip",
               5 * 1024 ** 2, r"ipadapter[_-]?plus", nodo="IPAdapterAdvanced",
               git="https://github.com/cubiq/ComfyUI_IPAdapter_plus"),
    Componente("modello_ipadapter", "IPAdapter Plus SDXL (ViT-H)", "modello",
               "il modello IPAdapter per i checkpoint SDXL (Pony, Illustrious, NoobAI…)",
               "models/ipadapter", "ip-adapter-plus_sdxl_vit-h.safetensors",
               "https://huggingface.co/h94/IP-Adapter/resolve/main/sdxl_models/ip-adapter-plus_sdxl_vit-h.safetensors",
               848 * 1024 ** 2, r"plus.*sdxl.*vit-?h"),
    Componente("clip_vision_vit_h", "CLIP Vision ViT-H", "modello",
               "il modello che «guarda» l'immagine di riferimento per IPAdapter",
               "models/clip_vision", "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors",
               "https://huggingface.co/h94/IP-Adapter/resolve/main/models/image_encoder/model.safetensors",
               2_528_373_448, r"vit-?h|laion2b-s32b"),
]


@dataclass
class Spazio:
    cartella: str
    libero: int
    serve: int                       # file + margine
    basta: bool


@dataclass
class StatoComponenti:
    comfy_dir: str | None
    mancanti: list[dict] = field(default_factory=list)
    presenti: list[str] = field(default_factory=list)
    da_caricare: list[str] = field(default_factory=list)   # nodi sul disco ma non caricati da ComfyUI
    spazio: list[Spazio] = field(default_factory=list)
    basta_spazio: bool = True
    totale: int = 0
    errore: str | None = None

    def dict(self):
        return asdict(self)


def _file_in(cartella: Path) -> list[str]:
    if not cartella.is_dir():
        return []
    return [f.name for f in cartella.rglob("*") if f.is_file() and not f.name.endswith(".parziale")]


def controlla(comfy_dir: str | None, modelli: dict[str, list[str]] | None = None,
              nodi_caricati: set[str] | None = None, elenco: list[Componente] | None = None) -> StatoComponenti:
    """Quali componenti mancano e se c'è spazio per installarli.
    `modelli` (elenchi di ComfyUI per cartella) e `nodi_caricati` (da /object_info) servono quando ComfyUI è acceso:
    contano anche i modelli in cartelle aggiunte con extra_model_paths e i nodi installati con un altro nome."""
    elenco = IPADAPTER if elenco is None else elenco
    s = StatoComponenti(comfy_dir=comfy_dir)
    if not comfy_dir or not Path(comfy_dir).is_dir():
        s.errore = "Non so dov'è ComfyUI: cercalo in Sistema → Connessione."
        return s
    base = Path(comfy_dir)
    for c in elenco:
        if c.tipo == "nodo":
            cartelle = [p.name for p in (base / c.cartella).iterdir() if p.is_dir()] \
                if (base / c.cartella).is_dir() else []
            sul_disco = any(re.search(c.riconosci, x, re.I) for x in cartelle)
            caricato = c.nodo in nodi_caricati if nodi_caricati is not None else None
            if caricato:
                s.presenti.append(c.id)
            elif sul_disco:
                s.presenti.append(c.id)
                if caricato is False:
                    s.da_caricare.append(c.id)
            else:
                s.mancanti.append(asdict(c))
        else:
            nomi = _file_in(base / c.cartella) + list((modelli or {}).get(Path(c.cartella).name, []))
            if any(re.search(c.riconosci, Path(n).name, re.I) for n in nomi):
                s.presenti.append(c.id)
            else:
                s.mancanti.append(asdict(c))
    s.totale = sum(m["byte"] for m in s.mancanti)
    s.spazio = spazio_per_disco(base, s.mancanti)
    s.basta_spazio = all(x.basta for x in s.spazio)
    return s


def gb(byte: int) -> str:
    return f"{byte / GB:.1f}".replace(".", ",")


def spazio_per_disco(base: Path, mancanti: list[dict]) -> list[Spazio]:
    """Lo spazio che serve su ogni disco (di solito uno solo: quello di ComfyUI)."""
    per_disco: dict[int, tuple[Path, int]] = {}
    dev_base = os.stat(base).st_dev
    for m in mancanti:
        d = base / m["cartella"]
        esistente = next((p for p in (d, *d.parents) if p.exists()), base)
        dev = os.stat(esistente).st_dev
        cartella, byte = per_disco.get(dev, (base if dev == dev_base else esistente, 0))
        per_disco[dev] = (cartella, byte + m["byte"])
    out = []
    for cartella, byte in per_disco.values():
        libero = shutil.disk_usage(cartella).free
        out.append(Spazio(str(cartella), libero, byte + MARGINE, libero >= byte + MARGINE))
    return out


def testo_spazio(s: StatoComponenti) -> str:
    """Il messaggio quando non c'è spazio."""
    corti = [x for x in s.spazio if not x.basta]
    return " ".join(f"Su {x.cartella} servono {gb(x.serve)} GB (compreso 1 GB di margine) e ne restano liberi "
                    f"{gb(x.libero)}: libera {gb(max(0, x.serve - x.libero))} GB e riprova."
                    for x in corti)


# ---------------------------------------------------------------- installazione

Avanzamento = Callable[[float, str], None]


class ErroreComponenti(Exception):
    pass


def scarica(c: dict, dest: Path, avanzamento: Avanzamento, annullato: Callable[[], bool]):
    """Scarica un modello in dest (passando per .parziale), con controllo di dimensione e impronta."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".parziale")
    h = hashlib.sha256()
    fatto = 0
    try:
        with httpx.stream("GET", c["url"], follow_redirects=True, timeout=httpx.Timeout(60, connect=20)) as r:
            if r.status_code >= 400:
                raise ErroreComponenti(f"Download di {c['nome']} non riuscito (HTTP {r.status_code}).")
            totale = int(r.headers.get("content-length") or 0) or c["byte"]
            impronta = _impronta_attesa(r)
            libero = shutil.disk_usage(dest.parent).free
            if totale > libero:
                raise ErroreComponenti(f"Non c'è spazio per {c['nome']}: servono {gb(totale)} GB, liberi "
                                       f"{gb(libero)}.")
            with open(tmp, "wb") as f:
                for blocco in r.iter_bytes(1 << 20):
                    if annullato():
                        raise ErroreComponenti("Installazione annullata")
                    f.write(blocco)
                    h.update(blocco)
                    fatto += len(blocco)
                    avanzamento(fatto / totale if totale else -1,
                                f"{c['nome']}: {gb(fatto)}/{gb(totale)} GB")
        if r.headers.get("content-length") and fatto != totale:
            raise ErroreComponenti(f"{c['nome']} è arrivato incompleto ({fatto} byte su {totale}): riprova.")
        if impronta and h.hexdigest() != impronta:
            raise ErroreComponenti(f"{c['nome']} è arrivato rovinato (impronta diversa): riprova.")
        tmp.replace(dest)
    except httpx.HTTPError as e:
        raise ErroreComponenti(f"Download di {c['nome']} interrotto: {e}. Controlla la connessione e riprova.") from None
    finally:
        tmp.unlink(missing_ok=True)


def _impronta_attesa(r: httpx.Response) -> str | None:
    """Hugging Face dà lo SHA-256 dei file grandi nell'intestazione x-linked-etag (o etag) del rimando."""
    for risposta in (*r.history, r):
        for chiave in ("x-linked-etag", "etag"):
            v = (risposta.headers.get(chiave) or "").strip('"').removeprefix("W/").strip('"')
            if re.fullmatch(r"[0-9a-f]{64}", v):
                return v
    return None


def installa_nodo(c: dict, base: Path, avanzamento: Avanzamento) -> str:
    """Il custom node: con git se c'è (così si aggiorna da ComfyUI-Manager), altrimenti dallo ZIP di GitHub."""
    dest = base / c["cartella"] / c["file"]
    if dest.exists():
        return "già presente"
    dest.parent.mkdir(parents=True, exist_ok=True)
    git = shutil.which("git")
    if git and c.get("git"):
        avanzamento(-1, f"{c['nome']}: git clone")
        r = subprocess.run([git, "clone", "--depth", "1", c["git"], str(dest)], capture_output=True, text=True,
                           timeout=300)
        if r.returncode == 0:
            return "con git"
        shutil.rmtree(dest, ignore_errors=True)       # si riprova con lo ZIP
    avanzamento(-1, f"{c['nome']}: scarico lo ZIP")
    try:
        with httpx.Client(follow_redirects=True, timeout=120) as h:
            r = h.get(c["url"])
            r.raise_for_status()
    except httpx.HTTPError as e:
        raise ErroreComponenti(f"Download di {c['nome']} non riuscito: {e}") from None
    tmp = dest.with_name(dest.name + ".parziale")
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        z.extractall(tmp)
    interne = [p for p in tmp.iterdir() if p.is_dir()]
    sorgente = interne[0] if len(interne) == 1 else tmp       # lo ZIP di GitHub ha una cartella <nome>-main
    shutil.move(str(sorgente), str(dest))
    shutil.rmtree(tmp, ignore_errors=True)
    return "dallo ZIP"


__all__ = ["IPADAPTER", "Componente", "ErroreComponenti", "StatoComponenti", "controlla", "installa_nodo", "scarica",
           "testo_spazio"]
