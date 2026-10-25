"""Controllo del sistema all'avvio: hardware, componenti installati, aggiornamenti e consigli.

Ogni controllo produce una voce con stato ok / avviso / errore / info e, se serve, cosa fare.
I controlli di rete (aggiornamenti) hanno un tempo massimo e non bloccano gli altri.
"""
from __future__ import annotations

import asyncio
import json
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

import httpx
import psutil

from .modelinfo import GB, analizza, consiglio_spazio

Esito = Literal["ok", "avviso", "errore", "info"]

# custom node: (cartella tipica, nodo che dimostra che è caricato, a cosa serve, obbligatorio)
CUSTOM_NODE = [
    ("ComfyUI_IPAdapter_plus", "IPAdapterAdvanced", "somiglianza al riferimento (Step 1)", True,
     "https://github.com/cubiq/ComfyUI_IPAdapter_plus"),
    ("comfyui_controlnet_aux", "DWPreprocessor", "pose delle scene a più personaggi (Step 4)", False,
     "https://github.com/Fannovel16/comfyui_controlnet_aux"),
    ("ComfyUI-Impact-Pack", "FaceDetailer", "ritocco dei volti (Step 4)", False,
     "https://github.com/ltdrdata/ComfyUI-Impact-Pack"),
    ("ComfyUI-Manager", None, "installare e aggiornare i custom node", False,
     "https://github.com/Comfy-Org/ComfyUI-Manager"),
]

MODELLI_SUPPORTO = [
    ("ipadapter", r"ip-?adapter.*(sdxl|xl)", "IPAdapter per SDXL", True,
     "ip-adapter-plus_sdxl_vit-h.safetensors"),
    ("clip_vision", r"vit-?h|clip-vit-h|laion2b", "CLIP Vision ViT-H (per IPAdapter)", True,
     "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"),
    ("controlnet", r"openpose|union", "ControlNet OpenPose SDXL (Step 4)", False,
     "controlnet-openpose-sdxl-1.0 (xinsir) o controlnet-union-sdxl-promax"),
]


@dataclass
class Voce:
    categoria: str
    nome: str
    esito: Esito
    dettaglio: str = ""
    azione: str | None = None
    link: str | None = None


@dataclass
class Rapporto:
    hardware: dict = field(default_factory=dict)
    voci: list[Voce] = field(default_factory=list)
    consigli: list[str] = field(default_factory=list)
    modelli: list[dict] = field(default_factory=list)
    aggiornamenti_controllati: bool = False

    def aggiungi(self, *a, **kw):
        self.voci.append(Voce(*a, **kw))

    def dict(self):
        d = asdict(self)
        d["riepilogo"] = {e: sum(1 for v in self.voci if v.esito == e) for e in ("ok", "avviso", "errore", "info")}
        return d


# ---------------------------------------------------------------- utilità

def esegui(cmd: list[str], timeout: float = 15, cwd: str | None = None) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd,
                           encoding="utf-8", errors="replace")
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return -1, str(e)


def gpu_nvidia_smi() -> list[dict]:
    if not shutil.which("nvidia-smi"):
        return []
    codice, out = esegui(["nvidia-smi", "--query-gpu=name,memory.total,memory.free,driver_version",
                          "--format=csv,noheader,nounits"], timeout=10)
    if codice != 0:
        return []
    gpu = []
    for riga in out.splitlines():
        parti = [p.strip() for p in riga.split(",")]
        if len(parti) == 4:
            try:
                gpu.append({"nome": parti[0], "vram_totale": int(parti[1]) * 1024 ** 2,
                            "vram_libera": int(parti[2]) * 1024 ** 2, "driver": parti[3]})
            except ValueError:
                continue
    return gpu


def gpu_da_comfy(dispositivi: list[dict]) -> list[dict]:
    out = []
    for d in dispositivi or []:
        nome = re.sub(r"^cuda:\d+\s*", "", d.get("name", "")).split(" : ")[0].strip()
        out.append({"nome": nome or d.get("name"), "tipo": d.get("type"),
                    "vram_totale": d.get("vram_total"), "vram_libera": d.get("vram_free")})
    return out


# ---------------------------------------------------------------- sezioni

def controlla_hardware(r: Rapporto, dispositivi_comfy: list[dict], cartelle: list[Path]):
    mem = psutil.virtual_memory()
    sistema = platform.system()
    apple = sistema == "Darwin" and platform.machine() == "arm64"
    gpu = gpu_da_comfy(dispositivi_comfy) or gpu_nvidia_smi()
    gpu = [g for g in gpu if g.get("tipo") not in ("cpu",)]
    r.hardware = {
        "sistema": f"{sistema} {platform.release()}", "architettura": platform.machine(),
        "cpu": platform.processor() or platform.machine(), "core": psutil.cpu_count(logical=False),
        "thread": psutil.cpu_count(), "ram_totale": mem.total, "ram_libera": mem.available,
        "gpu": gpu, "apple_silicon": apple, "dischi": []}

    if gpu:
        g = gpu[0]
        vram = (g.get("vram_totale") or 0) / GB
        r.aggiungi("Hardware", "Scheda video", "ok", f"{g['nome']} — {vram:.0f} GB di VRAM")
    elif apple:
        r.aggiungi("Hardware", "Scheda video", "info",
                   f"Apple Silicon: memoria unificata di {mem.total / GB:.0f} GB condivisa con la GPU (MPS)")
    else:
        r.aggiungi("Hardware", "Scheda video", "avviso", "Nessuna GPU rilevata: avvia ComfyUI per leggerla da lì",
                   "Senza GPU NVIDIA la generazione è molto lenta e l'addestramento non è praticabile.")

    ram = mem.total / GB
    esito: Esito = "ok" if ram >= 30 else "avviso" if ram >= 15 else "errore"
    r.aggiungi("Hardware", "Memoria RAM", esito, f"{ram:.0f} GB ({mem.available / GB:.0f} GB liberi)",
               None if esito == "ok" else "Con meno di 32 GB l'addestramento SDXL può usare il file di paging e "
                                          "rallentare molto: chiudi gli altri programmi mentre addestri.")

    visti = set()
    for c in cartelle:
        try:
            u = psutil.disk_usage(str(c))
        except OSError:
            continue
        chiave = (u.total, round(u.free / GB))
        if chiave in visti:
            continue
        visti.add(chiave)
        libero = u.free / GB
        r.hardware["dischi"].append({"cartella": str(c), "libero": u.free, "totale": u.total})
        esito = "ok" if libero >= 50 else "avviso" if libero >= 20 else "errore"
        r.aggiungi("Hardware", f"Spazio su disco ({c})", esito, f"{libero:.0f} GB liberi su {u.total / GB:.0f} GB",
                   None if esito == "ok" else "Ogni personaggio occupa circa 2-5 GB (immagini, cache, epoche del "
                                              "LoRA). Libera spazio o sposta i progetti su un altro disco.")


def controlla_software(r: Rapporto, comfy_dir: Path | None, comfy_codice: Path | None, versione: str | None,
                       nodi_caricati: set[str] | None, cartella_dati: Path):
    v = sys.version_info
    esito: Esito = "ok" if (3, 10) <= v[:2] <= (3, 13) else "avviso"
    r.aggiungi("Software", "Python di Comic Studio", esito, f"{v.major}.{v.minor}.{v.micro}")

    codice, out = esegui(["git", "--version"])
    if codice == 0:
        r.aggiungi("Software", "Git", "ok", out.replace("git version", "").strip())
    else:
        r.aggiungi("Software", "Git", "avviso", "non trovato",
                   "Serve per installare kohya e i custom node e per controllare gli aggiornamenti.",
                   "https://git-scm.com/downloads")

    if comfy_dir:
        tipo = "in esecuzione" if versione else "trovato, non avviato"
        r.aggiungi("Software", "ComfyUI", "ok" if versione else "avviso",
                   f"{versione or 'versione sconosciuta'} — {tipo} — {comfy_dir}",
                   None if versione else "Avvia ComfyUI per generare immagini e per controlli più precisi.")
    else:
        r.aggiungi("Software", "ComfyUI", "errore", "non trovato",
                   "Installa ComfyUI o indica la sua cartella nella pagina Connessione.",
                   "https://www.comfy.org/download")

    cartelle_nodi = []
    if comfy_dir and (comfy_dir / "custom_nodes").is_dir():
        cartelle_nodi = [p.name.lower() for p in (comfy_dir / "custom_nodes").iterdir() if p.is_dir()]
    for cartella, nodo, uso, obbligatorio, link in CUSTOM_NODE:
        presente_disco = any(cartella.lower() in c for c in cartelle_nodi)
        caricato = nodo in nodi_caricati if (nodo and nodi_caricati is not None) else None
        if caricato or (presente_disco and caricato is None):
            r.aggiungi("Custom node", cartella, "ok", f"installato — {uso}")
        elif presente_disco and caricato is False:
            r.aggiungi("Custom node", cartella, "errore", f"presente ma non caricato — {uso}",
                       "ComfyUI non riesce a caricarlo: guarda gli errori all'avvio di ComfyUI "
                       "o reinstallalo dal Manager.", link)
        else:
            r.aggiungi("Custom node", cartella, "errore" if obbligatorio else "info",
                       f"non installato — {uso}", "Installalo da ComfyUI-Manager o con git clone in custom_nodes.",
                       link)

    if comfy_dir:
        for sotto, regex, nome, obbligatorio, consigliato in MODELLI_SUPPORTO:
            d = comfy_dir / "models" / sotto
            trovati = [f.name for f in d.rglob("*") if f.is_file() and re.search(regex, f.name.lower())] \
                if d.is_dir() else []
            if trovati:
                r.aggiungi("Modelli di supporto", nome, "ok", ", ".join(trovati[:3]))
            else:
                r.aggiungi("Modelli di supporto", nome, "errore" if obbligatorio else "info", "non trovato",
                           f"Scarica {consigliato} in models/{sotto}.")

    kohya = cartella_dati / "strumenti" / "sd-scripts"
    if (kohya / "sdxl_train_network.py").exists():
        r.aggiungi("Software", "kohya sd-scripts", "ok", str(kohya))
    else:
        r.aggiungi("Software", "kohya sd-scripts", "info", "non ancora installato",
                   "Servirà nello Step 3 (Addestramento): il programma lo installerà da solo.")


def controlla_modelli(r: Rapporto, comfy_dir: Path | None):
    if not comfy_dir:
        return
    for sotto in ("checkpoints", "diffusion_models", "unet"):
        d = comfy_dir / "models" / sotto
        if not d.is_dir():
            continue
        for f in d.rglob("*"):
            if f.suffix.lower() not in (".safetensors", ".gguf", ".ckpt"):
                continue
            try:
                info = analizza(f)
            except OSError:
                continue
            voce = info.dict()
            voce["cartella"] = sotto
            r.modelli.append(voce)
            c = consiglio_spazio(info)
            if c:
                r.consigli.append(c)
            if info.formato == "ckpt":
                r.consigli.append(f"{info.file} è in formato .ckpt: preferisci la versione .safetensors "
                                  "(più sicura e più veloce da caricare).")


def consigli_hardware(r: Rapporto):
    gpu = r.hardware.get("gpu") or []
    vram = (gpu[0].get("vram_totale") or 0) / GB if gpu else 0
    nome = (gpu[0].get("nome") or "") if gpu else ""
    famiglie = {m.get("famiglia") for m in r.modelli}
    c = r.consigli

    if r.hardware.get("apple_silicon"):
        c.append("Su Mac la generazione funziona via MPS, ma l'addestramento dei LoRA con kohya è molto lento: "
                 "valuta di addestrare su un PC con GPU NVIDIA o con un servizio online.")
    elif not gpu:
        return
    elif vram <= 8.5:
        c.append(f"VRAM {vram:.0f} GB: per l'addestramento SDXL usa fp8 sul modello base, batch 1, "
                 "gradient checkpointing, cache dei latenti e Adafactor (sono le impostazioni predefinite).")
        c.append("VRAM 8 GB: in generazione evita di usare più di due IPAdapter insieme e tieni le vignette "
                 "intorno a 1 megapixel (832×1216 o 1216×832), poi ingrandisci con un upscaler.")
        if "flux" in famiglie:
            c.append("Hai modelli Flux: con 8 GB usa la versione GGUF Q4_K_S o Q5_K_S (custom node ComfyUI-GGUF) "
                     "e il text encoder T5 in fp8 o GGUF.")
    elif vram <= 12.5:
        c.append(f"VRAM {vram:.0f} GB: puoi addestrare SDXL in bf16 senza fp8, rank fino a 32, batch 1-2.")
        if "flux" in famiglie:
            c.append("Con Flux usa la versione fp8 o GGUF Q8_0.")
    else:
        c.append(f"VRAM {vram:.0f} GB: puoi addestrare in bf16 con batch 2-4 e rank 32-64.")
    if "laptop" in nome.lower():
        c.append("GPU di un portatile: tieni il PC collegato alla corrente e ben ventilato durante "
                 "l'addestramento, altrimenti rallenta per il calore.")


# ---------------------------------------------------------------- aggiornamenti (rete)

async def git_aggiornamento(cartella: Path) -> tuple[str, Esito, str] | None:
    """Confronta il commit locale con quello remoto, senza scaricare nulla."""
    if not (cartella / ".git").exists() or not shutil.which("git"):
        return None
    codice, locale = await asyncio.to_thread(esegui, ["git", "rev-parse", "HEAD"], 10, str(cartella))
    if codice != 0:
        return None
    codice, ramo = await asyncio.to_thread(esegui, ["git", "rev-parse", "--abbrev-ref", "HEAD"], 10, str(cartella))
    ramo = ramo if codice == 0 and ramo != "HEAD" else None
    codice, remoto = await asyncio.to_thread(esegui, ["git", "ls-remote", "origin", ramo or "HEAD"], 20, str(cartella))
    if codice != 0 or not remoto:
        return (cartella.name, "info", "impossibile contattare il repository remoto")
    hash_remoto = remoto.split()[0]
    if hash_remoto == locale:
        return (cartella.name, "ok", "aggiornato")
    return (cartella.name, "avviso", f"aggiornamento disponibile (locale {locale[:7]}, remoto {hash_remoto[:7]})")


async def ultima_release_comfy() -> str | None:
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://api.github.com/repos/comfyanonymous/ComfyUI/releases/latest",
                            headers={"Accept": "application/vnd.github+json"})
            if r.status_code == 200:
                return r.json().get("tag_name", "").lstrip("v") or None
    except httpx.HTTPError:
        return None
    return None


def confronta_versioni(a: str, b: str) -> int:
    def parti(v):
        return [int(x) for x in re.findall(r"\d+", v)[:3]]
    pa, pb = parti(a), parti(b)
    return (pa > pb) - (pa < pb)


async def librerie_obsolete() -> list[dict]:
    codice, out = await asyncio.to_thread(
        esegui, [sys.executable, "-m", "pip", "list", "--outdated", "--format=json", "--disable-pip-version-check"], 90)
    if codice != 0:
        return []
    try:
        return json.loads(out[out.index("["):])
    except ValueError:
        return []


async def controlla_aggiornamenti(r: Rapporto, comfy_dir: Path | None, comfy_codice: Path | None,
                                  versione: str | None, radice_app: Path):
    compiti = []
    nomi = []
    if comfy_codice:
        compiti.append(git_aggiornamento(comfy_codice))
        nomi.append("ComfyUI (git)")
    if comfy_dir and (comfy_dir / "custom_nodes").is_dir():
        for d in sorted((comfy_dir / "custom_nodes").iterdir()):
            if d.is_dir() and (d / ".git").exists():
                compiti.append(git_aggiornamento(d))
                nomi.append(f"custom node {d.name}")
    compiti.append(git_aggiornamento(radice_app))
    nomi.append("Comic Studio")
    risultati = await asyncio.gather(*compiti, return_exceptions=True)
    for nome, ris in zip(nomi, risultati):
        if isinstance(ris, tuple):
            r.aggiungi("Aggiornamenti", nome, ris[1], ris[2],
                       "Aggiorna da ComfyUI-Manager (o con git pull) quando non stai generando."
                       if ris[1] == "avviso" and nome != "Comic Studio" else
                       ("Scarica l'ultima versione con git pull nella cartella del programma." if ris[1] == "avviso"
                        else None))

    if versione:
        ultima = await ultima_release_comfy()
        if ultima and confronta_versioni(versione, ultima) < 0:
            r.aggiungi("Aggiornamenti", "ComfyUI (release)", "avviso",
                       f"installata {versione}, disponibile {ultima}",
                       "Aggiorna ComfyUI dal Manager, con update_comfyui.bat (portable) o dall'app Desktop.",
                       "https://github.com/comfyanonymous/ComfyUI/releases")
        elif ultima:
            r.aggiungi("Aggiornamenti", "ComfyUI (release)", "ok", f"{versione} è l'ultima versione")

    obsolete = await librerie_obsolete()
    if obsolete:
        elenco = ", ".join(f"{p['name']} {p['version']}→{p['latest_version']}" for p in obsolete[:8])
        r.aggiungi("Aggiornamenti", "Librerie di Comic Studio", "info", elenco,
                   "Si aggiornano da sole al prossimo avvio con avvia.bat / avvia.sh.")
    else:
        r.aggiungi("Aggiornamenti", "Librerie di Comic Studio", "ok", "aggiornate")
    r.aggiornamenti_controllati = True


# ---------------------------------------------------------------- insieme

async def diagnostica(comfy_dir: str | None, comfy_codice: str | None, versione: str | None,
                      dispositivi: list[dict], nodi_caricati: set[str] | None, cartella_dati: Path,
                      radice_app: Path, rete: bool = True, avanzamento=None) -> Rapporto:
    r = Rapporto()
    base = Path(comfy_dir) if comfy_dir else None
    codice = Path(comfy_codice) if comfy_codice else (base if base and (base / "main.py").exists() else None)

    def passo(v, t):
        if avanzamento:
            avanzamento(v, t)

    passo(0.05, "hardware")
    cartelle = [p for p in (cartella_dati, base) if p and p.exists()] or [Path.home()]
    await asyncio.to_thread(controlla_hardware, r, dispositivi, cartelle)
    passo(0.25, "componenti installati")
    await asyncio.to_thread(controlla_software, r, base, codice, versione, nodi_caricati, cartella_dati)
    passo(0.45, "modelli")
    await asyncio.to_thread(controlla_modelli, r, base)
    consigli_hardware(r)
    if rete:
        passo(0.6, "aggiornamenti (rete)")
        await controlla_aggiornamenti(r, base, codice, versione, radice_app)
    return r


__all__ = ["diagnostica", "Rapporto", "Voce", "confronta_versioni", "gpu_da_comfy"]
