"""Step 3 — Addestramento del LoRA di ogni personaggio con kohya sd-scripts.

- installazione di kohya in <cartella dati>/strumenti/sd-scripts, con il suo ambiente Python e PyTorch
- parametri con preset in base alla VRAM
- esecuzione con lettura in diretta di passi, epoche, velocità e loss
- test delle epoche con ComfyUI e scelta del LoRA finale, copiato in ComfyUI/models/loras

File: <progetto>/personaggi/<pid>/addestramento/
        config.json   stato.json   loss.json   dataset/ (immagini + .txt)   uscita/ (epoche)   test/
"""
from __future__ import annotations

import json
import os
import platform
import time
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .projects import ErroreProgetto

URL_KOHYA = "https://github.com/kohya-ss/sd-scripts.git"
ZIP_KOHYA = "https://codeload.github.com/kohya-ss/sd-scripts/zip/refs/heads/main"
TORCH = ["torch==2.6.0", "torchvision==0.21.0"]
INDICE_CUDA = "https://download.pytorch.org/whl/cu124"
INDICE_CPU = "https://download.pytorch.org/whl/cpu"

Preset = Literal["8gb", "equilibrato", "qualita", "personalizzato"]


# ---------------------------------------------------------------- kohya

@dataclass
class Kohya:
    cartella: Path
    python: Path

    def script(self, nome: str = "sdxl_train_network.py") -> Path:
        return self.cartella / nome


def cartella_kohya(dati: Path) -> Path:
    return dati / "strumenti" / "sd-scripts"


def python_venv(cartella: Path) -> Path:
    return cartella / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def trova_kohya(dati: Path) -> Kohya | None:
    c = cartella_kohya(dati)
    py = python_venv(c)
    if (c / "sdxl_train_network.py").exists() and py.exists():
        return Kohya(c, py)
    return None


def python_per_kohya() -> list[str] | None:
    """Un Python 3.10-3.12 con cui creare l'ambiente di kohya (3.10 è quello consigliato)."""
    candidati: list[list[str]] = []
    if os.name == "nt" and shutil.which("py"):
        candidati += [["py", f"-3.{v}"] for v in (10, 11, 12)]
    candidati += [[n] for n in ("python3.10", "python3.11", "python3.12") if shutil.which(n)]
    base = getattr(sys, "_base_executable", sys.executable)
    if Path(base).name.lower() == "pythonw.exe":          # Comic Studio installato su Windows
        base = str(Path(base).with_name("python.exe"))
    candidati += [[base], ["python3"], ["python"]]
    for c in candidati:
        try:
            r = subprocess.run(c + ["-c", "import sys, venv; print(sys.version_info[:2])"], capture_output=True,
                               text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            continue
        m = re.search(r"\((\d+), (\d+)\)", r.stdout)
        if r.returncode == 0 and m and (3, 10) <= (int(m.group(1)), int(m.group(2))) <= (3, 12):
            return c
    return None


def tipo_gpu() -> Literal["cuda", "mps", "cpu"]:
    if platform.system() == "Darwin":
        return "mps" if platform.machine() == "arm64" else "cpu"
    if shutil.which("nvidia-smi"):
        return "cuda"
    return "cpu"


def comandi_installazione(cartella: Path, python: list[str], gpu: str, git: bool) -> list[tuple[str, list[str], Path | None]]:
    """I passi dell'installazione: (descrizione, comando, cartella di lavoro). Il download senza git è a parte."""
    py = str(python_venv(cartella))
    passi: list[tuple[str, list[str], Path | None]] = []
    if git:
        if (cartella / ".git").exists():
            passi.append(("Aggiorno kohya sd-scripts", ["git", "pull", "--ff-only"], cartella))
        else:
            passi.append(("Scarico kohya sd-scripts", ["git", "clone", "--depth", "1", URL_KOHYA, str(cartella)], None))
    passi.append(("Creo l'ambiente Python di kohya", python + ["-m", "venv", str(cartella / "venv")], None))
    passi.append(("Aggiorno pip", [py, "-m", "pip", "install", "--upgrade", "pip"], cartella))
    torch = [py, "-m", "pip", "install", *TORCH]
    if gpu == "cuda":
        torch += ["--index-url", INDICE_CUDA]
    elif gpu == "cpu":
        torch += ["--index-url", INDICE_CPU]
    passi.append(("Installo PyTorch (circa 2,5 GB)", torch, cartella))
    passi.append(("Installo le librerie di kohya", [py, "-m", "pip", "install", "--upgrade", "-r", "requirements.txt"],
                  cartella))
    return passi


def verifica_kohya(k: Kohya) -> dict:
    codice = ("import json, torch; d = torch.cuda.is_available(); "
              "print(json.dumps({'torch': torch.__version__, 'cuda': d, "
              "'gpu': torch.cuda.get_device_name(0) if d else None, "
              "'mps': bool(getattr(torch.backends, 'mps', None) and torch.backends.mps.is_available())}))")
    try:
        r = subprocess.run([str(k.python), "-c", codice], capture_output=True, text=True, timeout=120, cwd=k.cartella)
        info = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else {"errore": r.stderr[-800:]}
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError) as e:
        info = {"errore": str(e)}
    commit = None
    if (k.cartella / ".git").exists() and shutil.which("git"):
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=k.cartella)
        commit = r.stdout.strip() or None
    return {**info, "commit": commit, "cartella": str(k.cartella)}


# ---------------------------------------------------------------- parametri

class ConfigAddestramento(BaseModel):
    preset: Preset = "8gb"
    checkpoint: str | None = None           # nome nel menu dei checkpoint di ComfyUI
    rank: int = Field(16, ge=1, le=256)
    alpha: float = Field(8, gt=0, le=256)
    learning_rate: float = Field(1e-4, gt=0, le=1)
    allena_text_encoder: bool = False
    learning_rate_te: float = Field(5e-5, gt=0, le=1)
    ottimizzatore: Literal["Adafactor", "AdamW8bit", "AdamW", "Prodigy"] = "Adafactor"
    scheduler: Literal["constant_with_warmup", "cosine", "cosine_with_restarts", "linear", "constant"] = "constant_with_warmup"
    warmup: int = Field(100, ge=0, le=5000)
    epoche: int = Field(10, ge=1, le=100)
    passi_obiettivo: int = Field(2000, ge=100, le=50000)
    ripetizioni: int | None = Field(None, ge=1, le=200)     # None = calcolate dai passi obiettivo
    risoluzione: int = Field(1024, ge=512, le=2048)
    batch: int = Field(1, ge=1, le=16)
    fp8: bool = True
    gradient_checkpointing: bool = True
    mescola_didascalie: bool = False         # incompatibile con la cache del text encoder
    noise_offset: float = Field(0.0, ge=0, le=1)
    min_snr_gamma: float | None = Field(5.0, ge=0, le=20)
    seme: int = 42
    argomenti_extra: str = ""


def preset(nome: Preset, base: ConfigAddestramento | None = None) -> ConfigAddestramento:
    c = (base or ConfigAddestramento()).model_copy()
    valori = {
        # Adafactor a passo fisso: 4e-4 (come i trainer di Civitai per SDXL). Con 1e-4 e alpha 8/rank 16 il LoRA
        # imparava troppo poco: la trigger word da sola non portava il personaggio
        "8gb": dict(rank=16, alpha=8, ottimizzatore="Adafactor", learning_rate=4e-4, batch=1, fp8=True,
                    gradient_checkpointing=True, allena_text_encoder=False, risoluzione=1024),
        "equilibrato": dict(rank=32, alpha=16, ottimizzatore="AdamW8bit", learning_rate=1e-4, batch=1, fp8=False,
                            gradient_checkpointing=True, allena_text_encoder=False, risoluzione=1024),
        "qualita": dict(rank=32, alpha=16, ottimizzatore="AdamW8bit", learning_rate=8e-5, batch=2, fp8=False,
                        gradient_checkpointing=True, allena_text_encoder=True, learning_rate_te=3e-5,
                        risoluzione=1024),
    }.get(nome)
    if valori:
        c = c.model_copy(update=valori)
    c.preset = nome
    return c


def preset_per_vram(vram_byte: int | None) -> Preset:
    gb = (vram_byte or 0) / 1024 ** 3
    if gb >= 15:
        return "qualita"
    if gb >= 11:
        return "equilibrato"
    return "8gb"


def ripetizioni(c: ConfigAddestramento, immagini: int) -> int:
    if c.ripetizioni:
        return c.ripetizioni
    return max(1, round(c.passi_obiettivo * c.batch / max(1, immagini * c.epoche)))


def passi_totali(c: ConfigAddestramento, immagini: int) -> int:
    return -(-immagini * ripetizioni(c, immagini) // c.batch) * c.epoche


def toml_dataset(cartella: Path, c: ConfigAddestramento, immagini: int) -> str:
    mescola = "true" if c.mescola_didascalie else "false"
    return (
        "[general]\n"
        "enable_bucket = true\n"
        "bucket_reso_steps = 64\n"
        "min_bucket_reso = 512\n"
        "max_bucket_reso = 2048\n"
        'caption_extension = ".txt"\n'
        f"shuffle_caption = {mescola}\n"
        "keep_tokens = 1\n\n"
        "[[datasets]]\n"
        f"resolution = {c.risoluzione}\n"
        f"batch_size = {c.batch}\n\n"
        "  [[datasets.subsets]]\n"
        f"  image_dir = '{cartella.as_posix()}'\n"
        f"  num_repeats = {ripetizioni(c, immagini)}\n"
    )


def argomenti(k: Kohya, c: ConfigAddestramento, checkpoint: Path, toml: Path, uscita: Path, nome: str) -> list[str]:
    a = [str(k.python), "-u", str(k.script()),
         "--pretrained_model_name_or_path", str(checkpoint),
         "--dataset_config", str(toml),
         "--output_dir", str(uscita), "--output_name", nome, "--save_model_as", "safetensors",
         "--network_module", "networks.lora",
         "--network_dim", str(c.rank), "--network_alpha", f"{c.alpha:g}",
         "--max_train_epochs", str(c.epoche), "--save_every_n_epochs", "1",
         "--optimizer_type", c.ottimizzatore,
         "--lr_scheduler", c.scheduler, "--lr_warmup_steps", str(c.warmup),
         "--mixed_precision", "bf16", "--save_precision", "bf16", "--no_half_vae",
         "--cache_latents", "--cache_latents_to_disk", "--sdpa",
         "--seed", str(c.seme), "--max_data_loader_n_workers", "1"]
    if c.allena_text_encoder:
        a += ["--unet_lr", f"{c.learning_rate:g}", "--text_encoder_lr", f"{c.learning_rate_te:g}",
              "--learning_rate", f"{c.learning_rate:g}"]
    else:
        a += ["--network_train_unet_only", "--learning_rate", f"{c.learning_rate:g}"]
        if not c.mescola_didascalie:
            a.append("--cache_text_encoder_outputs")
    if c.ottimizzatore == "Adafactor":
        a += ["--optimizer_args", "scale_parameter=False", "relative_step=False", "warmup_init=False"]
    if c.ottimizzatore == "Prodigy":
        a += ["--optimizer_args", "decouple=True", "use_bias_correction=True", "safeguard_warmup=True"]
    if c.gradient_checkpointing:
        a.append("--gradient_checkpointing")
    if c.fp8:
        a.append("--fp8_base")
    if c.noise_offset:
        a += ["--noise_offset", f"{c.noise_offset:g}"]
    if c.min_snr_gamma:
        a += ["--min_snr_gamma", f"{c.min_snr_gamma:g}"]
    if c.argomenti_extra.strip():
        import shlex
        a += shlex.split(c.argomenti_extra, posix=os.name != "nt")
    return a


# ---------------------------------------------------------------- lettura dell'uscita di kohya

RE_PASSI = re.compile(r"steps:\s*\d+%.*?(\d+)/(\d+)\s*\[([\d:]+)<([\d:?]+),\s*([\d.]+)\s*(s/it|it/s)")
RE_LOSS = re.compile(r"avr_loss=([\d.]+(?:e[-+]?\d+)?)", re.I)
RE_EPOCA = re.compile(r"\bepoch (\d+)/(\d+)")
RE_SALVATAGGIO = re.compile(r"saving checkpoint:\s*(.+?\.safetensors)", re.I)


@dataclass
class Avanzamento:
    passo: int = 0
    totale: int = 0
    epoca: int = 0
    epoche: int = 0
    velocita: str = ""
    rimanente: str = ""
    loss: float | None = None
    salvato: str | None = None


def leggi_riga(riga: str, a: Avanzamento) -> bool:
    """Aggiorna lo stato con una riga di kohya; True se è cambiato qualcosa di utile."""
    cambiato = False
    if m := RE_PASSI.search(riga):
        a.passo, a.totale = int(m.group(1)), int(m.group(2))
        a.rimanente = m.group(4)
        a.velocita = f"{m.group(5)} {m.group(6)}"
        cambiato = True
    if m := RE_LOSS.search(riga):
        a.loss = float(m.group(1))
        cambiato = True
    if m := RE_EPOCA.search(riga):
        a.epoca, a.epoche = int(m.group(1)), int(m.group(2))
        cambiato = True
    if m := RE_SALVATAGGIO.search(riga):
        a.salvato = m.group(1).strip()
        cambiato = True
    return cambiato


def spiega_errore(testo: str) -> str | None:
    t = testo.lower()
    if "out of memory" in t:
        return ("Memoria della scheda video esaurita. Chiudi ComfyUI e gli altri programmi che usano la GPU, oppure "
                "usa il preset «8 GB» e abbassa il rank a 8 o la risoluzione a 896.")
    if "no module named" in t:
        m = re.search(r"no module named '([^']+)'", t)
        return (f"Manca la libreria «{m.group(1) if m else '?'}» nell'ambiente di kohya: premi «Reinstalla» "
                "nella sezione del trainer.")
    if "torch not compiled with cuda" in t or "cuda is not available" in t:
        return "PyTorch non vede la scheda video NVIDIA: reinstalla kohya o aggiorna i driver della GPU."
    if "safetensors_rust.safetensorerror" in t or "header too large" in t:
        return "Il file del checkpoint sembra rovinato o non è un modello SDXL: scegline un altro."
    return None


# ---------------------------------------------------------------- epoche

def file_epoche(uscita: Path, nome: str) -> list[dict]:
    """Le epoche salvate: nome-000003.safetensors ... e nome.safetensors (l'ultima)."""
    if not uscita.is_dir():
        return []
    out = []
    finale = uscita / f"{nome}.safetensors"
    for f in uscita.glob(f"{nome}-*.safetensors"):
        m = re.fullmatch(rf"{re.escape(nome)}-(\d+)\.safetensors", f.name)
        if m:
            out.append({"epoca": int(m.group(1)), "file": f.name, "dimensione": f.stat().st_size, "creato": f.stat().st_mtime})
    if finale.exists():
        ultima = max((e["epoca"] for e in out), default=0) + 1
        out.append({"epoca": ultima, "file": finale.name, "dimensione": finale.stat().st_size,
                    "creato": finale.stat().st_mtime, "ultima": True})
    return sorted(out, key=lambda e: e["epoca"])


def epoche_da_provare(epoche: list[int], quante: int = 4) -> list[int]:
    if len(epoche) <= quante:
        return epoche
    n = len(epoche)
    indici = sorted({round((n - 1) * f) for f in (0.4, 0.6, 0.8, 1.0)})
    return [epoche[i] for i in indici]


class VersioneLora(BaseModel):
    """Un LoRA del personaggio messo in ComfyUI (models/loras/comic_studio): lo storico non si sovrascrive."""
    versione: int
    file: str                              # nome nel menu dei LoRA di ComfyUI (comic_studio/<trigger>_v3.safetensors)
    nome_file: str                         # nome del file nella cartella comic_studio
    epoca: int | None = None
    creato: float = Field(default_factory=time.time)
    punteggio: float | None = None         # somiglianza al riferimento nella prova delle epoche, se c'era
    addestramento: float | None = None     # inizio dell'addestramento da cui viene
    parametri: dict = Field(default_factory=dict)
    automatica: bool = False               # salvata da sola a fine addestramento (l'ultima epoca)
    nota: str = ""


class RegistroAddestramento(BaseModel):
    inizio: float
    durata: float | None = None
    esito: str = "in corso"
    epoche_salvate: int = 0
    parametri: dict = Field(default_factory=dict)


def riassunto_parametri(c: "ConfigAddestramento", immagini: int) -> dict:
    return {"checkpoint": c.checkpoint, "preset": c.preset, "rank": c.rank, "alpha": c.alpha,
            "learning_rate": c.learning_rate, "ottimizzatore": c.ottimizzatore, "epoche": c.epoche,
            "immagini": immagini, "passi": passi_totali(c, immagini) if immagini else None,
            "text_encoder": c.allena_text_encoder}


class StatoAddestramento(BaseModel):
    lora_finale: str | None = None         # nome nel menu dei LoRA di ComfyUI
    epoca_finale: int | None = None
    origine: Literal["addestrato", "esistente"] | None = None
    ultimo_avvio: float | None = None
    ultima_durata: float | None = None
    ultimo_esito: str | None = None
    test: dict[str, dict] = Field(default_factory=dict)    # "epoca" -> {"immagini": [...], "punteggio": x}
    storico: list[VersioneLora] = Field(default_factory=list)            # i LoRA salvati in ComfyUI, dal primo
    addestramenti: list[RegistroAddestramento] = Field(default_factory=list)
    prompt_test: list[str] = Field(default_factory=lambda: [
        "{trigger}, {genere}, solo, running in the rain, from side, city street, night",
        "{trigger}, {genere}, solo, sitting in a car, laughing, upper body",
        "{trigger}, {genere}, solo, standing on a rooftop, arms crossed, full body, sunset",
    ])


class ArchivioAddestramento:
    def __init__(self, progetti):
        self.progetti = progetti

    def cartella(self, pid: str, cid: str) -> Path:
        return self.progetti.cartella_personaggio(pid, cid) / "addestramento"

    def _leggi(self, f: Path, modello):
        try:
            return modello.model_validate_json(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return modello()

    def _scrivi(self, f: Path, m: BaseModel):
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(m.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(f)

    def config(self, pid, cid) -> ConfigAddestramento:
        c = self._leggi(self.cartella(pid, cid) / "config.json", ConfigAddestramento)
        if c.preset == "8gb" and c.ottimizzatore == "Adafactor" and c.learning_rate == 1e-4:
            c.learning_rate = 4e-4          # preset «8 GB» delle versioni prima della 0.27 (imparava troppo poco)
        return c

    def salva_config(self, pid, cid, c: ConfigAddestramento):
        self._scrivi(self.cartella(pid, cid) / "config.json", c)

    def stato(self, pid, cid) -> StatoAddestramento:
        return self._leggi(self.cartella(pid, cid) / "stato.json", StatoAddestramento)

    def salva_stato(self, pid, cid, s: StatoAddestramento):
        self._scrivi(self.cartella(pid, cid) / "stato.json", s)

    def loss(self, pid, cid) -> list[list[float]]:
        try:
            return json.loads((self.cartella(pid, cid) / "loss.json").read_text())
        except (OSError, ValueError):
            return []

    def salva_loss(self, pid, cid, punti: list[list[float]]):
        f = self.cartella(pid, cid) / "loss.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(punti))


def risolvi_checkpoint(comfy_dir: str | None, nome: str | None) -> Path:
    if not nome:
        raise ErroreProgetto("Scegli il checkpoint su cui addestrare (lo stesso che userai per il fumetto).")
    p = Path(nome)
    if p.is_absolute() and p.exists():
        return p
    if comfy_dir:
        for sotto in ("checkpoints", "Stable-diffusion"):
            f = Path(comfy_dir) / "models" / sotto / nome
            if f.exists():
                return f
    raise ErroreProgetto(f"Non trovo il file del checkpoint «{nome}» nella cartella di ComfyUI.")


def cartella_lora_comfy(comfy_dir: str | None) -> Path:
    if not comfy_dir:
        raise ErroreProgetto("Serve la cartella di ComfyUI (pagina Sistema) per copiarci i LoRA.")
    d = Path(comfy_dir) / "models" / "loras" / "comic_studio"
    d.mkdir(parents=True, exist_ok=True)
    return d


def durata(s: float) -> str:
    s = int(s)
    if s < 90:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min"
    return f"{s // 3600} h {s % 3600 // 60} min"

