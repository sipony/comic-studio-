"""Ricerca automatica di ComfyUI sullo stesso computer.

Strategia, dalla più affidabile alla meno:
  1. istanze in esecuzione: interroga le porte note e legge da /system_stats il percorso di avvio
  2. processi attivi che eseguono main.py di ComfyUI (psutil)
  3. file di configurazione di ComfyUI Desktop (basePath)
  4. cartelle tipiche per Windows, macOS e Linux
"""
from __future__ import annotations

import json
import os
import platform
import string
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

PORTE = [8188, 8000, 8189, 8190, 8288]
CARTELLE_MODELLI = ["checkpoints", "loras", "ipadapter", "clip_vision", "controlnet", "vae", "upscale_models"]


@dataclass
class Installazione:
    cartella: str                     # cartella che contiene models/, input/, output/
    codice: str | None = None         # cartella con main.py (diversa dalla precedente in ComfyUI Desktop)
    origine: str = ""                 # come è stata trovata
    tipo: str = "sconosciuto"         # portable, desktop, manuale
    url: str | None = None            # se è in esecuzione
    versione: str | None = None
    modelli: dict[str, int] = field(default_factory=dict)

    def dict(self):
        return asdict(self)


@dataclass
class Istanza:
    url: str
    versione: str | None
    argv: list[str]
    dispositivi: list[dict]
    python: str | None


# ---------------------------------------------------------------- verifiche

def e_cartella_comfy(p: Path) -> bool:
    """Una cartella ComfyUI ha models/ e almeno uno tra main.py, input/, output/, custom_nodes/."""
    try:
        if not (p / "models").is_dir():
            return False
        return any((p / x).exists() for x in ("main.py", "input", "output", "custom_nodes"))
    except OSError:
        return False


def conta_modelli(cartella: Path) -> dict[str, int]:
    estensioni = {".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf", ".onnx"}
    conteggio = {}
    for nome in CARTELLE_MODELLI:
        d = cartella / "models" / nome
        n = 0
        if d.is_dir():
            for radice, _, files in os.walk(d):
                n += sum(1 for f in files if Path(f).suffix.lower() in estensioni)
        conteggio[nome] = n
    return conteggio


def tipo_installazione(codice: Path | None, cartella: Path) -> str:
    if codice and (codice.parent / "python_embeded").is_dir():
        return "portable"
    if (cartella / ".venv").is_dir() or (cartella / "user" / "default" / "comfy.settings.json").exists():
        return "desktop" if not (cartella / "main.py").exists() else "manuale"
    return "manuale"


# ---------------------------------------------------------------- 1. istanze in esecuzione

def interroga(url: str, timeout: float = 1.5) -> Istanza | None:
    try:
        r = httpx.get(url.rstrip("/") + "/system_stats", timeout=timeout)
        if r.status_code != 200:
            return None
        d = r.json()
    except (httpx.HTTPError, ValueError):
        return None
    s = d.get("system", {})
    if "devices" not in d and "comfyui_version" not in s:
        return None
    return Istanza(url=url.rstrip("/"), versione=s.get("comfyui_version"), argv=s.get("argv") or [],
                   dispositivi=d.get("devices", []), python=s.get("python_version"))


def istanze_attive(extra: list[str] | None = None) -> list[Istanza]:
    url = [f"http://127.0.0.1:{p}" for p in PORTE] + list(extra or [])
    visti, trovate = set(), []
    for u in url:
        u = u.rstrip("/")
        if u in visti:
            continue
        visti.add(u)
        ist = interroga(u)
        if ist:
            trovate.append(ist)
    return trovate


def cartella_da_argv(argv: list[str]) -> Path | None:
    """Dal comando di avvio ricava la cartella del codice; --base-directory ha la precedenza."""
    for i, a in enumerate(argv):
        if a == "--base-directory" and i + 1 < len(argv):
            return Path(argv[i + 1])
    for a in argv:
        if a.endswith("main.py"):
            return Path(a).resolve().parent
    return None


# ---------------------------------------------------------------- 2. processi

def cartelle_da_processi() -> list[Path]:
    try:
        import psutil
    except ImportError:
        return []
    trovate = []
    for proc in psutil.process_iter(["cmdline", "cwd"]):
        try:
            cmd = proc.info.get("cmdline") or []
            if not any(c.endswith("main.py") for c in cmd):
                continue
            if not any("comfy" in c.lower() for c in cmd) and "comfy" not in (proc.info.get("cwd") or "").lower():
                continue
            p = cartella_da_argv(cmd)
            if p and not p.is_absolute() and proc.info.get("cwd"):
                p = Path(proc.info["cwd"]) / p
            if p:
                trovate.append(p)
        except Exception:  # processi che spariscono o senza permessi
            continue
    return trovate


# ---------------------------------------------------------------- 3. ComfyUI Desktop

def file_config_desktop() -> list[Path]:
    home = Path.home()
    sistema = platform.system()
    if sistema == "Windows":
        base = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        return [base / "ComfyUI" / "config.json"]
    if sistema == "Darwin":
        return [home / "Library" / "Application Support" / "ComfyUI" / "config.json"]
    return [Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "ComfyUI" / "config.json"]


def cartelle_desktop() -> list[Path]:
    trovate = []
    for f in file_config_desktop():
        try:
            base = json.loads(f.read_text(encoding="utf-8")).get("basePath")
            if base:
                trovate.append(Path(base))
        except (OSError, ValueError):
            continue
    return trovate


# ---------------------------------------------------------------- 4. cartelle tipiche

def cartelle_tipiche() -> list[Path]:
    home = Path.home()
    radici = [home, home / "Documents", home / "Desktop", home / "Downloads", home / "AI", home / "ai"]
    if platform.system() == "Windows":
        for lettera in string.ascii_uppercase[2:8]:   # C: ... H:
            r = Path(f"{lettera}:\\")
            if r.exists():
                radici += [r, r / "AI", r / "Programmi", r / "Program Files"]
    else:
        radici += [Path("/opt"), Path("/workspace"), Path("/srv"), home / "Applications"]
    candidate = []
    for r in radici:
        try:
            if not r.is_dir():
                continue
            for figlio in r.iterdir():
                if "comfy" not in figlio.name.lower() or not figlio.is_dir():
                    continue
                candidate.append(figlio)
                candidate.append(figlio / "ComfyUI")     # versione portable: ComfyUI_windows_portable/ComfyUI
        except OSError:
            continue
    return candidate


# ---------------------------------------------------------------- insieme

def risolvi(p: Path) -> tuple[Path, Path | None] | None:
    """Da un percorso candidato ricava (cartella dati, cartella codice)."""
    for c in (p, p / "ComfyUI"):
        if e_cartella_comfy(c):
            return c, (c if (c / "main.py").exists() else None)
    return None


def cerca(url_extra: list[str] | None = None, cartelle_extra: list[str] | None = None) -> list[Installazione]:
    risultati: dict[str, Installazione] = {}

    def aggiungi(p: Path, origine: str, ist: Istanza | None = None):
        r = risolvi(p)
        if not r:
            return
        cartella, codice = r
        chiave = os.path.normcase(str(cartella.resolve()))
        if chiave in risultati:
            if ist and not risultati[chiave].url:
                risultati[chiave].url, risultati[chiave].versione = ist.url, ist.versione
            return
        risultati[chiave] = Installazione(
            cartella=str(cartella.resolve()), codice=str(codice.resolve()) if codice else None,
            origine=origine, tipo=tipo_installazione(codice, cartella),
            url=ist.url if ist else None, versione=ist.versione if ist else None)

    attive_rete = istanze_attive(url_extra)
    for ist in attive_rete:
        p = cartella_da_argv(ist.argv)
        if p:
            aggiungi(p, f"in esecuzione su {ist.url}", ist)
    for p in cartelle_da_processi():
        aggiungi(p, "processo attivo")
    for p in cartelle_desktop():
        aggiungi(p, "ComfyUI Desktop")
    for p in cartelle_extra or []:
        aggiungi(Path(p).expanduser(), "indicata a mano")
    for p in cartelle_tipiche():
        aggiungi(p, "cartella trovata sul disco")

    for inst in risultati.values():
        inst.modelli = conta_modelli(Path(inst.cartella))
    # un'istanza in esecuzione che non ha rivelato la sua cartella: se l'installazione è una sola, è lei
    if attive_rete and not any(i.url for i in risultati.values()) and len(risultati) == 1:
        unica = next(iter(risultati.values()))
        unica.url, unica.versione = attive_rete[0].url, attive_rete[0].versione
    return sorted(risultati.values(), key=lambda i: (i.url is None, -sum(i.modelli.values())))
