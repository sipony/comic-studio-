"""Costruisce gli installer di Comic Studio per Windows, macOS e Linux.

Gira su Linux (anche nella CI) e produce, in installer/dist/:
  ComicStudio-<versione>-Windows-Setup.exe        installer NSIS (senza permessi di amministratore)
  ComicStudio-<versione>-macOS-AppleSilicon.zip   «Comic Studio.app» per Mac con chip M1/M2/M3/M4
  ComicStudio-<versione>-macOS-Intel.zip          «Comic Studio.app» per Mac Intel
  ComicStudio-<versione>-Linux-x86_64.AppImage    un file che si avvia con un doppio clic
  comic-studio_<versione>_amd64.deb               pacchetto per Ubuntu, Debian, Mint

Ogni pacchetto contiene un Python completo (python-build-standalone), le librerie già installate per quella
piattaforma e l'interfaccia già compilata: chi installa non ha bisogno di Python, Node o del terminale.

Serve: Python 3.10+, Node (solo se l'interfaccia non è già compilata), makensis (apt install nsis) per Windows,
dpkg-deb per il .deb. uv e appimagetool vengono scaricati da soli.

Uso:  python installer/costruisci.py [--solo windows,macos-arm64,macos-x64,appimage,deb]
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

QUI = Path(__file__).resolve().parent
RADICE = QUI.parent
CACHE = QUI / ".cache"
LAVORO = QUI / "build"
USCITA = QUI / "dist"
DIST_UI = RADICE / "frontend" / "dist" / "comic-studio" / "browser"

# Python incluso negli installer: stessa versione per tutti (i .pyc compilati valgono ovunque)
PBS_TAG = "20261021"
PBS_PYTHON = "3.12.15"
PBS_SHA256 = {
    "x86_64-pc-windows-msvc": "aac5d331fc3307343f95928fdbea4583f0d53973d08c7e1d081884fbd229a0e1",
    "aarch64-apple-darwin": "7b8d00b751db21cea87dc551a8f8165147c5fbc5251d5537d7e5497dde00a219",
    "x86_64-apple-darwin": "f12e0504397683d6be0745ffd4c39ef45a455cec169adf35c628840d06133773",
    "x86_64-unknown-linux-gnu": "6d7521138fd33afddc1ccd08abb007d9a2829e38117c2576f9efdc0ec73ce772",
}
URL_PBS = ("https://github.com/astral-sh/python-build-standalone/releases/download/"
           "{tag}/cpython-{py}+{tag}-{triple}-install_only_stripped.tar.gz")
URL_APPIMAGETOOL = "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
MACOS_MINIMO = "13.0"
ID_APP = "io.github.sipony.comicstudio"
DESCRIZIONE = "Fumetti con personaggi coerenti usando ComfyUI"


@dataclass
class Bersaglio:
    nome: str          # windows, macos-arm64, macos-x64, linux
    triple: str        # python-build-standalone e uv --python-platform
    windows: bool = False

    @property
    def site_packages(self) -> str:
        return "Lib/site-packages" if self.windows else "lib/python3.12/site-packages"


BERSAGLI = {
    "windows": Bersaglio("windows", "x86_64-pc-windows-msvc", windows=True),
    "macos-arm64": Bersaglio("macos-arm64", "aarch64-apple-darwin"),
    "macos-x64": Bersaglio("macos-x64", "x86_64-apple-darwin"),
    "linux": Bersaglio("linux", "x86_64-unknown-linux-gnu"),
}
PACCHETTI = {"windows": "windows", "macos-arm64": "macos-arm64", "macos-x64": "macos-x64",
             "appimage": "linux", "deb": "linux"}


def passo(t: str):
    print(f"\n== {t}", flush=True)


def esegui(cmd: list[str], **k):
    print("   $", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **k)


def versione() -> str:
    testo = (RADICE / "backend" / "app" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__\s*=\s*"([^"]+)"', testo).group(1)


def scarica(url: str, file: Path, sha256: str | None = None) -> Path:
    if not file.exists():
        file.parent.mkdir(parents=True, exist_ok=True)
        print(f"   scarico {url}", flush=True)
        tmp = file.with_suffix(file.suffix + ".part")
        with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
        tmp.replace(file)
    if sha256:
        trovato = hashlib.sha256(file.read_bytes()).hexdigest()
        if trovato != sha256:
            file.unlink()
            raise SystemExit(f"Checksum errato per {file.name}: {trovato}")
    return file


def uv() -> list[str]:
    if shutil.which("uv"):
        return ["uv"]
    try:
        subprocess.run([sys.executable, "-m", "uv", "--version"], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        esegui([sys.executable, "-m", "pip", "install", "-q", "uv"])
    return [sys.executable, "-m", "uv"]


# ---------------------------------------------------------------- contenuto comune

def interfaccia():
    if (DIST_UI / "index.html").exists():
        return
    passo("Compilo l'interfaccia")
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        raise SystemExit("Serve Node.js per compilare l'interfaccia (oppure compilala prima con «npx ng build»).")
    esegui([npm, "ci"], cwd=RADICE / "frontend")
    esegui([npm, "run", "build"], cwd=RADICE / "frontend")


def icone(dest: Path) -> dict[str, Path]:
    """Icona dell'app (come favicon.svg) in PNG, ICO e ICNS."""
    from PIL import Image, ImageDraw
    dest.mkdir(parents=True, exist_ok=True)
    n = 1024
    sfumatura = Image.new("RGB", (n, n))
    px = sfumatura.load()
    a, b = (0x8B, 0x5C, 0xF6), (0xF9, 0x73, 0x16)
    for y in range(n):
        for x in range(n):
            t = (x + y) / (2 * (n - 1))
            px[x, y] = tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    maschera = Image.new("L", (n, n), 0)
    ImageDraw.Draw(maschera).rounded_rectangle((0, 0, n - 1, n - 1), radius=n // 4, fill=255)
    img.paste(sfumatura, (0, 0), maschera)
    s = n / 64
    for (x, y, w, h, op) in ((12, 14, 18, 16, .95), (34, 14, 18, 36, .8), (12, 34, 18, 16, .65)):
        strato = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        ImageDraw.Draw(strato).rounded_rectangle((x * s, y * s, (x + w) * s, (y + h) * s), radius=3 * s,
                                                 fill=(255, 255, 255, round(255 * op)))
        img = Image.alpha_composite(img, strato)
    out = {"png": dest / "comic-studio.png", "png512": dest / "comic-studio-512.png",
           "ico": dest / "comic-studio.ico", "icns": dest / "ComicStudio.icns"}
    img.resize((256, 256), Image.LANCZOS).save(out["png"])
    img.resize((512, 512), Image.LANCZOS).save(out["png512"])
    img.save(out["ico"], sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    img.save(out["icns"])
    return out


LANCIATORE = '''"""Avvio di Comic Studio installato (vedi backend/app/installato.py)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))
from app.installato import main  # noqa: E402

main()
'''

CHIUDI = '''"""Usato dall'installer: chiude Comic Studio se è aperto, così i file si possono sostituire."""
import json
import time
import urllib.request

for porta in range(8765, 8776):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{porta}/api/sistema", timeout=1) as r:
            if "versione" not in json.loads(r.read().decode("utf-8")):
                continue
        richiesta = urllib.request.Request(f"http://127.0.0.1:{porta}/api/esci", data=b"{}", method="POST",
                                           headers={"Content-Type": "application/json"})
        urllib.request.urlopen(richiesta, timeout=5).close()
    except Exception:
        continue
    for _ in range(60):            # aspetta che si sia chiuso davvero (i file non devono essere in uso)
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{porta}/api/sistema", timeout=1).close()
            time.sleep(0.25)
        except Exception:
            break
    time.sleep(1)
'''

ESCLUSI_STDLIB = ("test", "idlelib", "tkinter", "turtledemo", "lib2to3", "pydoc_data")


def prepara_radice(b: Bersaglio, linux_py: Path | None) -> Path:
    """build/<bersaglio>/radice con python/ (librerie incluse) e app/."""
    passo(f"Preparo il contenuto per {b.nome}")
    radice = LAVORO / b.nome / "radice"
    if radice.exists():
        shutil.rmtree(radice)
    radice.mkdir(parents=True)

    archivio = scarica(URL_PBS.format(tag=PBS_TAG, py=PBS_PYTHON, triple=b.triple),
                       CACHE / f"cpython-{PBS_PYTHON}+{PBS_TAG}-{b.triple}.tar.gz", PBS_SHA256[b.triple])
    with tarfile.open(archivio) as t:
        t.extractall(radice, filter="tar")
    py = radice / "python"
    stdlib = py / "Lib" if b.windows else py / "lib" / "python3.12"
    for nome in ESCLUSI_STDLIB:
        shutil.rmtree(stdlib / nome, ignore_errors=True)
    shutil.rmtree(py / "share" / "man", ignore_errors=True)
    if not b.windows:
        for d in (py / "lib").glob("t[ck]*8.6"):
            shutil.rmtree(d, ignore_errors=True)
    else:
        shutil.rmtree(py / "tcl", ignore_errors=True)

    sp = py / b.site_packages
    env = {**os.environ, "MACOSX_DEPLOYMENT_TARGET": MACOS_MINIMO}
    esegui([*uv(), "pip", "install", "--quiet", "--target", sp, "--python-platform", b.triple,
            "--python-version", "3.12", "--only-binary", ":all:", "--no-cache",
            "-r", RADICE / "backend" / "requirements.txt"], env=env)
    for d in sp.glob("*/tests"):
        shutil.rmtree(d, ignore_errors=True)
    if b.windows:
        runtime_msvc(py)

    app = radice / "app"
    shutil.copytree(RADICE / "backend" / "app", app / "backend" / "app",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(DIST_UI, app / "frontend" / "dist" / "comic-studio" / "browser")
    (app / "comic_studio.pyw").write_text(LANCIATORE, encoding="utf-8")
    (app / "chiudi.py").write_text(CHIUDI, encoding="utf-8")
    shutil.copy(RADICE / "LICENSE", app / "LICENSE")
    (app / "VERSIONE").write_text(versione(), encoding="utf-8")

    if linux_py:   # avvio più rapido: .pyc già pronti (unchecked-hash: valgono anche dopo la copia)
        esegui([linux_py, "-m", "compileall", "-q", "-j", "0", "--invalidation-mode", "unchecked-hash",
                app / "backend", sp, stdlib], stdout=subprocess.DEVNULL)
    return radice


def runtime_msvc(py: Path):
    """onnxruntime vuole msvcp140*.dll, che non tutti i Windows hanno: li mettiamo accanto a python.exe."""
    cartella = CACHE / "msvc-runtime"
    if not list(cartella.glob("*.whl")):
        esegui([sys.executable, "-m", "pip", "download", "-q", "msvc-runtime", "--platform", "win_amd64",
                "--python-version", "3.12", "--only-binary=:all:", "--no-deps", "-d", cartella])
    with zipfile.ZipFile(next(cartella.glob("*.whl"))) as z:
        for info in z.infolist():
            nome = Path(info.filename)
            if nome.parent.name == "data" and nome.suffix.lower() == ".dll" and not (py / nome.name).exists():
                (py / nome.name).write_bytes(z.read(info))


def python_linux_per_compilare() -> Path:
    cartella = LAVORO / "py-host"
    py = cartella / "python" / "bin" / "python3"
    if not py.exists():
        t = "x86_64-unknown-linux-gnu"
        archivio = scarica(URL_PBS.format(tag=PBS_TAG, py=PBS_PYTHON, triple=t),
                           CACHE / f"cpython-{PBS_PYTHON}+{PBS_TAG}-{t}.tar.gz", PBS_SHA256[t])
        with tarfile.open(archivio) as tf:
            tf.extractall(cartella, filter="tar")
    return py


def dimensione_kb(cartella: Path) -> int:
    return sum(f.stat().st_size for f in cartella.rglob("*") if f.is_file() and not f.is_symlink()) // 1024


# ---------------------------------------------------------------- Windows

NSI = r'''Unicode true
ManifestDPIAware true
!include "MUI2.nsh"

!define NOME "Comic Studio"
!define VERSIONE "{versione}"
!define CHIAVE "Software\Microsoft\Windows\CurrentVersion\Uninstall\ComicStudio"

Name "${{NOME}}"
OutFile "{uscita}"
InstallDir "$LOCALAPPDATA\Programs\ComicStudio"
InstallDirRegKey HKCU "Software\ComicStudio" "Cartella"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 64
BrandingText "${{NOME}} ${{VERSIONE}}"

VIProductVersion "{versione4}"
VIAddVersionKey /LANG=1040 "ProductName" "${{NOME}}"
VIAddVersionKey /LANG=1040 "FileDescription" "Installazione di ${{NOME}}"
VIAddVersionKey /LANG=1040 "FileVersion" "${{VERSIONE}}"
VIAddVersionKey /LANG=1040 "ProductVersion" "${{VERSIONE}}"
VIAddVersionKey /LANG=1040 "LegalCopyright" "Comic Studio"

!define MUI_ICON "{icona}"
!define MUI_UNICON "{icona}"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TEXT "Questa procedura installa ${{NOME}} ${{VERSIONE}} sul computer.$\r$\n$\r$\nNon servono Python, Node o il terminale: è tutto incluso. Non servono neanche i permessi di amministratore.$\r$\n$\r$\nI tuoi progetti restano nella cartella ComicStudio della tua cartella utente, anche se in futuro disinstalli il programma."
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Avvia Comic Studio"
!define MUI_FINISHPAGE_RUN_FUNCTION Avvia
!define MUI_UNCONFIRMPAGE_TEXT_TOP "Comic Studio verrà rimosso. I tuoi progetti, i LoRA addestrati e le impostazioni nella cartella $PROFILE\ComicStudio NON vengono cancellati."

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Italian"

Function Avvia
  Exec '"$INSTDIR\python\pythonw.exe" -s "$INSTDIR\app\comic_studio.pyw"'
FunctionEnd

!macro CHIUDI_APERTO
  IfFileExists "$INSTDIR\python\python.exe" 0 +4
    DetailPrint "Chiudo Comic Studio se è aperto..."
    nsExec::Exec '"$INSTDIR\python\python.exe" -s "$INSTDIR\app\chiudi.py"'
    Sleep 500
!macroend

Section "Comic Studio"
  SetOutPath "$INSTDIR"
  !insertmacro CHIUDI_APERTO
  DetailPrint "Rimuovo la versione precedente..."
  RMDir /r "$INSTDIR\app"
  RMDir /r "$INSTDIR\python"
  SetOutPath "$INSTDIR"
  File /r "{radice}\*"
  File "/oname=comic-studio.ico" "{icona}"
  WriteUninstaller "$INSTDIR\Disinstalla.exe"

  CreateShortCut "$SMPROGRAMS\Comic Studio.lnk" "$INSTDIR\python\pythonw.exe" '-s "$INSTDIR\app\comic_studio.pyw"' "$INSTDIR\comic-studio.ico" 0 SW_SHOWNORMAL "" "Comic Studio"
  CreateShortCut "$DESKTOP\Comic Studio.lnk" "$INSTDIR\python\pythonw.exe" '-s "$INSTDIR\app\comic_studio.pyw"' "$INSTDIR\comic-studio.ico" 0 SW_SHOWNORMAL "" "Comic Studio"

  WriteRegStr HKCU "Software\ComicStudio" "Cartella" "$INSTDIR"
  WriteRegStr HKCU "${{CHIAVE}}" "DisplayName" "${{NOME}}"
  WriteRegStr HKCU "${{CHIAVE}}" "DisplayVersion" "${{VERSIONE}}"
  WriteRegStr HKCU "${{CHIAVE}}" "Publisher" "Comic Studio"
  WriteRegStr HKCU "${{CHIAVE}}" "DisplayIcon" "$INSTDIR\comic-studio.ico"
  WriteRegStr HKCU "${{CHIAVE}}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${{CHIAVE}}" "UninstallString" '"$INSTDIR\Disinstalla.exe"'
  WriteRegStr HKCU "${{CHIAVE}}" "QuietUninstallString" '"$INSTDIR\Disinstalla.exe" /S'
  WriteRegDWORD HKCU "${{CHIAVE}}" "NoModify" 1
  WriteRegDWORD HKCU "${{CHIAVE}}" "NoRepair" 1
  WriteRegDWORD HKCU "${{CHIAVE}}" "EstimatedSize" {dimensione}
SectionEnd

Section "Uninstall"
  !insertmacro CHIUDI_APERTO
  Delete "$SMPROGRAMS\Comic Studio.lnk"
  Delete "$DESKTOP\Comic Studio.lnk"
  RMDir /r "$INSTDIR\app"
  RMDir /r "$INSTDIR\python"
  Delete "$INSTDIR\comic-studio.ico"
  Delete "$INSTDIR\Disinstalla.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "${{CHIAVE}}"
  DeleteRegKey HKCU "Software\ComicStudio"
SectionEnd
'''


def pacchetto_windows(radice: Path, ic: dict[str, Path]) -> Path:
    passo("Installer per Windows (NSIS)")
    if not shutil.which("makensis"):
        raise SystemExit("Manca makensis: installalo con «sudo apt install nsis».")
    v = versione()
    numeri = (re.findall(r"\d+", v) + ["0"] * 4)[:4]
    uscita = USCITA / f"ComicStudio-{v}-Windows-Setup.exe"
    nsi = LAVORO / "windows" / "comic-studio.nsi"
    nsi.write_text(NSI.format(versione=v, versione4=".".join(numeri), uscita=uscita, icona=ic["ico"],
                              radice=radice, dimensione=dimensione_kb(radice)), encoding="utf-8")
    esegui(["makensis", "-V2", "-INPUTCHARSET", "UTF8", nsi])
    return uscita


# ---------------------------------------------------------------- macOS

PLIST = '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Comic Studio</string>
  <key>CFBundleDisplayName</key><string>Comic Studio</string>
  <key>CFBundleIdentifier</key><string>{id}</string>
  <key>CFBundleVersion</key><string>{versione}</string>
  <key>CFBundleShortVersionString</key><string>{versione}</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>ComicStudio</string>
  <key>CFBundleIconFile</key><string>ComicStudio</string>
  <key>LSMinimumSystemVersion</key><string>{minimo}</string>
  <key>LSUIElement</key><true/>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSApplicationCategoryType</key><string>public.app-category.graphics-design</string>
</dict>
</plist>
'''

AVVIO_MAC = '''#!/bin/bash
# Comic Studio: avvia il server con il Python incluso e apre il browser
QUI="$(cd "$(dirname "$0")/../Resources" && pwd)"
exec "$QUI/python/bin/python3" -s "$QUI/app/comic_studio.pyw" "$@"
'''


def zip_con_permessi(cartella: Path, zipf: Path):
    """Zip che conserva i permessi di esecuzione e i collegamenti simbolici (li rispetta l'Utility Archivio)."""
    with zipfile.ZipFile(zipf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(cartella.rglob("*")):
            nome = str(Path(cartella.name) / f.relative_to(cartella))
            st = f.lstat()
            info = zipfile.ZipInfo(nome + ("/" if f.is_dir() and not f.is_symlink() else ""),
                                   time.localtime(st.st_mtime)[:6])
            info.create_system = 3
            if f.is_symlink():
                info.external_attr = (stat.S_IFLNK | 0o755) << 16
                z.writestr(info, os.readlink(f))
            elif f.is_dir():
                info.external_attr = (stat.S_IFDIR | 0o755) << 16 | 0x10
                z.writestr(info, b"")
            else:
                info.external_attr = (stat.S_IFREG | (0o755 if st.st_mode & 0o111 else 0o644)) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, f.read_bytes())


def pacchetto_mac(b: Bersaglio, radice: Path, ic: dict[str, Path]) -> Path:
    passo(f"App per macOS ({b.nome})")
    v = versione()
    cartella = LAVORO / b.nome / "pacchetto"
    if cartella.exists():
        shutil.rmtree(cartella)
    app = cartella / "Comic Studio.app" / "Contents"
    (app / "MacOS").mkdir(parents=True)
    shutil.copytree(radice, app / "Resources", symlinks=True)
    shutil.copy(ic["icns"], app / "Resources" / "ComicStudio.icns")
    (app / "Info.plist").write_text(PLIST.format(id=ID_APP, versione=v, minimo=MACOS_MINIMO), encoding="utf-8")
    eseg = app / "MacOS" / "ComicStudio"
    eseg.write_text(AVVIO_MAC, encoding="utf-8")
    eseg.chmod(0o755)
    (app / "PkgInfo").write_text("APPL????")
    nome = "AppleSilicon" if b.triple.startswith("aarch64") else "Intel"
    uscita = USCITA / f"ComicStudio-{v}-macOS-{nome}.zip"
    zip_con_permessi(cartella / "Comic Studio.app", uscita)
    return uscita


# ---------------------------------------------------------------- Linux

DESKTOP = '''[Desktop Entry]
Type=Application
Name=Comic Studio
Comment={descrizione}
Exec={exec}
Icon=comic-studio
Terminal=false
Categories=Graphics;
StartupNotify=false
'''

APPRUN = '''#!/bin/sh
QUI="$(dirname "$(readlink -f "$0")")"
export APPDIR="${APPDIR:-$QUI}"
exec "$QUI/usr/python/bin/python3" -s "$QUI/usr/app/comic_studio.pyw" "$@"
'''

AVVIO_DEB = '''#!/bin/sh
exec /opt/comic-studio/python/bin/python3 -s /opt/comic-studio/app/comic_studio.pyw "$@"
'''


def pacchetto_appimage(radice: Path, ic: dict[str, Path]) -> Path:
    passo("AppImage per Linux")
    v = versione()
    appdir = LAVORO / "linux" / "ComicStudio.AppDir"
    if appdir.exists():
        shutil.rmtree(appdir)
    (appdir / "usr").mkdir(parents=True)
    for nome in ("python", "app"):
        shutil.copytree(radice / nome, appdir / "usr" / nome, symlinks=True)
    (appdir / "AppRun").write_text(APPRUN)
    (appdir / "AppRun").chmod(0o755)
    (appdir / "comic-studio.desktop").write_text(DESKTOP.format(descrizione=DESCRIZIONE, exec="comic-studio"))
    shutil.copy(ic["png"], appdir / "comic-studio.png")
    shutil.copy(ic["png"], appdir / ".DirIcon")
    strumento = scarica(URL_APPIMAGETOOL, CACHE / "appimagetool-x86_64.AppImage")
    strumento.chmod(0o755)
    uscita = USCITA / f"ComicStudio-{v}-Linux-x86_64.AppImage"
    esegui([strumento, "--no-appstream", appdir, uscita],
           env={**os.environ, "ARCH": "x86_64", "APPIMAGE_EXTRACT_AND_RUN": "1"})
    return uscita


def pacchetto_deb(radice: Path, ic: dict[str, Path]) -> Path:
    passo("Pacchetto .deb (Ubuntu, Debian, Mint)")
    if not shutil.which("dpkg-deb"):
        raise SystemExit("Manca dpkg-deb.")
    v = versione()
    base = LAVORO / "linux" / "deb"
    if base.exists():
        shutil.rmtree(base)
    opt = base / "opt" / "comic-studio"
    opt.mkdir(parents=True)
    for nome in ("python", "app"):
        shutil.copytree(radice / nome, opt / nome, symlinks=True)
    bin_ = base / "usr" / "bin" / "comic-studio"
    bin_.parent.mkdir(parents=True)
    bin_.write_text(AVVIO_DEB)
    bin_.chmod(0o755)
    app_dir = base / "usr" / "share" / "applications"
    app_dir.mkdir(parents=True)
    (app_dir / "comic-studio.desktop").write_text(DESKTOP.format(descrizione=DESCRIZIONE, exec="comic-studio"))
    for lato, src in ((256, ic["png"]), (512, ic["png512"])):
        d = base / "usr" / "share" / "icons" / "hicolor" / f"{lato}x{lato}" / "apps"
        d.mkdir(parents=True)
        shutil.copy(src, d / "comic-studio.png")
    (base / "DEBIAN").mkdir()
    (base / "DEBIAN" / "control").write_text(
        f"Package: comic-studio\nVersion: {v}\nArchitecture: amd64\nMaintainer: Comic Studio <noreply@github.com>\n"
        f"Installed-Size: {dimensione_kb(base)}\nSection: graphics\nPriority: optional\n"
        "Recommends: xdg-utils, git\n"
        f"Description: {DESCRIZIONE}\n"
        " Dataset, didascalie, addestramento dei LoRA e tavole a fumetti, con Python incluso.\n")
    postrm = base / "DEBIAN" / "postrm"
    postrm.write_text('#!/bin/sh\nset -e\n# i .pyc creati durante l\'uso non sono nel pacchetto\n'
                      'if [ "$1" = remove ] || [ "$1" = purge ]; then rm -rf /opt/comic-studio; fi\n')
    postrm.chmod(0o755)
    uscita = USCITA / f"comic-studio_{v}_amd64.deb"
    esegui(["dpkg-deb", "--root-owner-group", "-Zxz", "--build", base, uscita])
    return uscita


# ---------------------------------------------------------------- principale

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--solo", default=",".join(PACCHETTI), help="pacchetti da costruire, separati da virgole")
    a = ap.parse_args()
    voluti = [p.strip() for p in a.solo.split(",") if p.strip()]
    sconosciuti = set(voluti) - set(PACCHETTI)
    if sconosciuti:
        raise SystemExit(f"Pacchetti sconosciuti: {', '.join(sorted(sconosciuti))}")

    inizio = time.time()
    USCITA.mkdir(parents=True, exist_ok=True)
    interfaccia()
    ic = icone(LAVORO / "icone")
    host = python_linux_per_compilare()
    radici: dict[str, Path] = {}
    prodotti = []
    for p in voluti:
        b = BERSAGLI[PACCHETTI[p]]
        if b.nome not in radici:
            radici[b.nome] = prepara_radice(b, host)
        r = radici[b.nome]
        if p == "windows":
            prodotti.append(pacchetto_windows(r, ic))
        elif p.startswith("macos"):
            prodotti.append(pacchetto_mac(b, r, ic))
        elif p == "appimage":
            prodotti.append(pacchetto_appimage(r, ic))
        elif p == "deb":
            prodotti.append(pacchetto_deb(r, ic))

    passo(f"Fatto in {time.time() - inizio:.0f} s")
    somme = []
    for f in prodotti:
        h = hashlib.sha256(f.read_bytes()).hexdigest()
        somme.append(f"{h}  {f.name}")
        print(f"   {f.name:52} {f.stat().st_size / 2**20:7.1f} MB")
    (USCITA / "SHA256SUMS.txt").write_text("\n".join(somme) + "\n")


if __name__ == "__main__":
    main()
