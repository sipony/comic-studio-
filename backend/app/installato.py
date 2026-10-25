"""Avvio di Comic Studio installato con l'installer (Windows, app macOS, AppImage o .deb su Linux).

Niente terminale:
- l'uscita va in <cartella dati>/comicstudio.log
- su Windows i programmi avviati da Comic Studio (git, pip, kohya, nvidia-smi…) non aprono finestre nere
- se Comic Studio è già aperto si apre solo il browser; se la porta 8765 è di un altro programma si usa la successiva
- un errore all'avvio compare in una finestra di messaggio del sistema
- con l'AppImage, al primo avvio Comic Studio si aggiunge al menu delle applicazioni
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
import traceback
import webbrowser
from pathlib import Path

PORTE = range(8765, 8776)
TITOLO = "Comic Studio"


def cartella_dati() -> Path:
    env = os.environ.get("COMIC_STUDIO_HOME")
    return Path(env).expanduser() if env else Path.home() / "ComicStudio"


def apri_registro() -> Path:
    dati = cartella_dati()
    dati.mkdir(parents=True, exist_ok=True)
    log = dati / "comicstudio.log"
    try:
        if log.exists() and log.stat().st_size > 5 * 1024 ** 2:
            log.replace(log.with_suffix(".log.1"))
    except OSError:
        pass
    f = open(log, "a", encoding="utf-8", buffering=1, errors="replace")
    sys.stdout = sys.stderr = f
    return log


def nascondi_console_dei_figli():
    """Windows: senza questo ogni comando avviato da pythonw.exe aprirebbe una finestra del terminale."""
    if os.name != "nt":
        return
    nessuna = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    originale = subprocess.Popen.__init__

    def init(self, *a, **k):
        k["creationflags"] = (k.get("creationflags") or 0) | nessuna
        originale(self, *a, **k)

    subprocess.Popen.__init__ = init


def messaggio(testo: str):
    """Una finestra di errore del sistema operativo."""
    try:
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, testo, TITOLO, 0x10)
        elif platform.system() == "Darwin":
            subprocess.run(["osascript", "-e", f"display dialog {json.dumps(testo)} with title {json.dumps(TITOLO)} "
                                               'buttons {"OK"} default button 1 with icon stop'], timeout=600)
        else:
            for cmd in (["zenity", "--error", "--title", TITOLO, "--text", testo],
                        ["kdialog", "--title", TITOLO, "--error", testo],
                        ["notify-send", TITOLO, testo]):
                if shutil.which(cmd[0]):
                    subprocess.run(cmd, timeout=600)
                    break
    except Exception:  # noqa: BLE001 - se neanche il messaggio funziona resta il registro
        traceback.print_exc()


def integra_menu_linux():
    """AppImage: aggiunge Comic Studio al menu delle applicazioni (e lo aggiorna se il file è stato spostato)."""
    appimage, appdir = os.environ.get("APPIMAGE"), os.environ.get("APPDIR")
    if not appimage or not appdir:
        return
    dati = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    desktop = dati / "applications" / "comic-studio.desktop"
    icona = dati / "icons" / "hicolor" / "256x256" / "apps" / "comic-studio.png"
    voce = ("[Desktop Entry]\nType=Application\nName=Comic Studio\nComment=Fumetti con personaggi coerenti usando ComfyUI\n"
            f'Exec="{appimage}"\nIcon=comic-studio\nTerminal=false\nCategories=Graphics;\n')
    try:
        if not desktop.exists() or desktop.read_text(encoding="utf-8") != voce:
            desktop.parent.mkdir(parents=True, exist_ok=True)
            desktop.write_text(voce, encoding="utf-8")
            icona.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(Path(appdir) / "comic-studio.png", icona)
            print(f"Aggiunto al menu delle applicazioni: {desktop}")
    except OSError as e:
        print(f"Menu delle applicazioni non aggiornato: {e}")


def main():
    log = apri_registro()
    from . import __version__
    print(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} Comic Studio {__version__} · Python {platform.python_version()} "
          f"· {platform.system()} {platform.release()} {platform.machine()}")
    nascondi_console_dei_figli()
    integra_menu_linux()
    try:
        from .__main__ import e_comic_studio, porta_libera, servi
        for porta in PORTE:
            if porta_libera("127.0.0.1", porta):
                break
            if e_comic_studio(porta):
                print(f"Comic Studio è già aperto sulla porta {porta}: apro il browser")
                webbrowser.open(f"http://127.0.0.1:{porta}")
                return
        else:
            raise RuntimeError(f"Le porte {PORTE.start}-{PORTE.stop - 1} sono tutte occupate da altri programmi.")
        print(f"Comic Studio su http://127.0.0.1:{porta}")
        servi("127.0.0.1", porta, apri_browser=True)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        messaggio(f"Comic Studio non è riuscito ad avviarsi:\n\n{e}\n\nTrovi i dettagli in:\n{log}")
        sys.exit(1)


if __name__ == "__main__":
    main()
