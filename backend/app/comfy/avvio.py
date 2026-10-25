"""Avvio di ComfyUI da Comic Studio.

- se ComfyUI è già in esecuzione, Comic Studio ci si aggancia e basta
- altrimenti lo avvia con il comando giusto per il tipo di installazione:
    portable   python_embeded/python.exe -s ComfyUI/main.py --windows-standalone-build
    manuale    <venv di ComfyUI>/python main.py
    Desktop    l'app ComfyUI (Windows / macOS)
  oppure con un comando scritto a mano nelle impostazioni
- ComfyUI gira come processo separato: chiudere Comic Studio non lo chiude.
  La sua uscita va in <cartella dati>/comfyui.log, che Comic Studio legge e mostra nella console.
"""
from __future__ import annotations

import os
import platform
import shlex
import shutil
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


class ErroreAvvio(Exception):
    pass


@dataclass
class Comando:
    argomenti: list[str]
    cartella: Path | None
    descrizione: str
    porta: int
    app_desktop: bool = False      # l'app Desktop sceglie da sola come avviarsi


def porta_da_url(url: str | None, predefinita: int = 8188) -> int:
    try:
        p = urlparse(url or "").port
        return p or predefinita
    except ValueError:
        return predefinita


def _python_venv(c: Path) -> Path | None:
    for nome in ("venv", ".venv", "env"):
        for rel in ("Scripts/python.exe", "bin/python"):
            f = c / nome / rel
            if f.exists():
                return f
    return None


def eseguibile_desktop() -> list[str] | None:
    sistema = platform.system()
    if sistema == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Programs"
        for f in (base / "@comfyorgcomfyui-electron" / "ComfyUI.exe", base / "ComfyUI" / "ComfyUI.exe"):
            if f.exists():
                return [str(f)]
    elif sistema == "Darwin":
        if Path("/Applications/ComfyUI.app").exists():
            return ["open", "-a", "ComfyUI"]
    return None


def comando(cartella: str | None, codice: str | None, tipo: str, url: str | None,
            personalizzato: str | None = None, extra: str = "") -> Comando:
    """Il comando per avviare un'installazione di ComfyUI."""
    argomenti_extra = shlex.split(extra, posix=os.name != "nt") if extra.strip() else []
    # le anteprime durante il campionamento, per vederle in Comic Studio
    anteprime = [] if "--preview-method" in argomenti_extra else ["--preview-method", "auto"]
    if personalizzato and personalizzato.strip():
        parti = shlex.split(personalizzato, posix=os.name != "nt")
        return Comando(parti + argomenti_extra, Path(cartella) if cartella else None, "comando personalizzato",
                       porta_da_url(url))
    if not cartella:
        raise ErroreAvvio("Non so dove sia ComfyUI: indicalo nella pagina Sistema → Connessione.")
    dati = Path(cartella)
    sorgente = Path(codice) if codice else (dati if (dati / "main.py").exists() else None)

    if tipo == "desktop" or (sorgente is None and (dati / "user").exists()):
        exe = eseguibile_desktop()
        if not exe:
            raise ErroreAvvio("È ComfyUI Desktop ma non trovo l'app da avviare: aprila tu, Comic Studio si aggancia "
                              "da solo, oppure scrivi il comando di avvio nelle impostazioni.")
        return Comando(exe, None, "app ComfyUI Desktop", porta_da_url(url, 8000), app_desktop=True)

    if sorgente is None:
        raise ErroreAvvio(f"In {cartella} non trovo main.py di ComfyUI: scrivi il comando di avvio nelle impostazioni.")
    porta = porta_da_url(url)
    embedded = sorgente.parent / "python_embeded" / ("python.exe" if os.name == "nt" else "python")
    if embedded.exists():
        return Comando([str(embedded), "-s", str(sorgente / "main.py"), "--windows-standalone-build",
                        "--port", str(porta), *anteprime, *argomenti_extra], sorgente.parent, "ComfyUI portable", porta)
    py = _python_venv(sorgente) or _python_venv(sorgente.parent)
    if py is None:
        trovato = shutil.which("python3") or shutil.which("python")
        if not trovato:
            raise ErroreAvvio("Non trovo il Python di ComfyUI: scrivi il comando di avvio nelle impostazioni.")
        py = Path(trovato)
        descrizione = "ComfyUI con il Python di sistema"
    else:
        descrizione = "ComfyUI con il suo ambiente Python"
    return Comando([str(py), "main.py", "--port", str(porta), *anteprime, *argomenti_extra], sorgente, descrizione,
                   porta)


def avvia(c: Comando, log: Path, ambiente: dict[str, str] | None = None) -> int:
    """Avvia ComfyUI staccato da Comic Studio; restituisce il PID."""
    log.parent.mkdir(parents=True, exist_ok=True)
    uscita = open(log, "ab", buffering=0)
    uscita.write(f"\n===== avvio: {' '.join(c.argomenti)}\n".encode())
    opzioni: dict = {}
    if os.name == "nt":
        opzioni["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        opzioni["start_new_session"] = True
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", **(ambiente or {})}
    try:
        p = subprocess.Popen(c.argomenti, cwd=str(c.cartella) if c.cartella else None, stdout=uscita,
                             stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env, **opzioni)
    except OSError as e:
        raise ErroreAvvio(f"Non riesco ad avviare ComfyUI: {e}") from None
    finally:
        uscita.close()
    return p.pid


def ferma(pid: int) -> bool:
    try:
        import psutil
        p = psutil.Process(pid)
        figli = p.children(recursive=True)
        p.terminate()
        for f in figli:
            try:
                f.terminate()
            except psutil.Error:
                pass
        _, vivi = psutil.wait_procs([p, *figli], timeout=10)
        for v in vivi:
            v.kill()
        return True
    except Exception:  # noqa: BLE001 - già chiuso o senza permessi
        return False


def vivo(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        import psutil
        p = psutil.Process(pid)
        return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
    except Exception:  # noqa: BLE001
        return False


class LettoreLog:
    """Legge le righe nuove di comfyui.log a ogni chiamata."""

    def __init__(self, file: Path):
        self.file = file
        self.posizione = file.stat().st_size if file.exists() else 0
        self.resto = b""

    def nuove(self) -> list[str]:
        try:
            dim = self.file.stat().st_size
        except OSError:
            return []
        if dim < self.posizione:        # file ricreato
            self.posizione = 0
        if dim == self.posizione:
            return []
        with open(self.file, "rb") as f:
            f.seek(self.posizione)
            dati = f.read(dim - self.posizione)
        self.posizione = dim
        testo = self.resto + dati
        righe = testo.replace(b"\r", b"\n").split(b"\n")
        self.resto = righe.pop()
        return [r.decode("utf-8", "replace").rstrip() for r in righe if r.strip()]


def salva_pid(file: Path, pid: int):
    """Ricorda il processo avviato, così si può fermare anche dopo aver riaperto Comic Studio."""
    try:
        import psutil
        creato = psutil.Process(pid).create_time()
    except Exception:  # noqa: BLE001
        creato = None
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps({"pid": pid, "creato": creato}), encoding="utf-8")


def leggi_pid(file: Path) -> int | None:
    """Il PID salvato, solo se quel processo è ancora lo stesso (i PID vengono riusati)."""
    try:
        dati = json.loads(file.read_text(encoding="utf-8"))
        pid = int(dati["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not vivo(pid):
        return None
    try:
        import psutil
        if dati.get("creato") and abs(psutil.Process(pid).create_time() - dati["creato"]) > 1:
            return None
    except Exception:  # noqa: BLE001
        return None
    return pid


def livello_riga(riga: str) -> str:
    """Livello di log di una riga scritta da ComfyUI."""
    r = riga.lower()
    if "traceback" in r or r.startswith(("error", "exception", "!!! exception")) or "error:" in r:
        return "errore"
    if r.startswith("warning") or "warning:" in r or "import failed" in r:
        return "avviso"
    if "to see the gui go to" in r or "starting server" in r:
        return "ok"
    return "debug"


def spiega_errore(righe: list[str], porta: int) -> str:
    """Una spiegazione in italiano a partire dalle ultime righe scritte da ComfyUI."""
    testo = "\n".join(righe)
    basso = testo.lower()
    import re
    m = re.search(r"No module named '([\w.\-]+)'", testo)
    if m:
        return (f"Manca il pacchetto Python «{m.group(1)}» nell'ambiente di ComfyUI: installa i requisiti "
                "(pip install -r requirements.txt con il Python di ComfyUI) o aggiorna ComfyUI.")
    if "address already in use" in basso or "10048" in basso or "only one usage of each socket" in basso:
        return (f"La porta {porta} è già occupata da un altro programma: chiudilo, oppure cambia porta "
                "nell'indirizzo di ComfyUI (es. http://127.0.0.1:8189).")
    if "torch not compiled with cuda" in basso or "found no nvidia driver" in basso:
        return ("Il PyTorch di ComfyUI non vede la scheda NVIDIA: aggiorna il driver, oppure aggiungi "
                "--cpu agli argomenti (molto più lento).")
    if "out of memory" in basso:
        return "Memoria della GPU esaurita già all'avvio: aggiungi --lowvram agli argomenti di avvio."
    if "permission denied" in basso or "access is denied" in basso:
        return "Permessi insufficienti per avviare ComfyUI in quella cartella."
    ultime = [r for r in righe if r.strip()][-3:]
    return ("Ultime righe: " + " | ".join(ultime)) if ultime else "ComfyUI non ha scritto niente: controlla il comando."
