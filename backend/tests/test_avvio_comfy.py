"""Avvio di ComfyUI da Comic Studio: comando per tipo di installazione, avvio, aggancio, arresto."""
import os
import socket
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.comfy import avvio, discovery
from app.main import crea_app
from app.settings import Archivio
from app.state import App
from conftest import crea_cartella_comfy

# un main.py che si comporta come ComfyUI quanto basta: scrive qualcosa e risponde a /system_stats
MAIN_FINTO = r'''
import json, os, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer
porta = int(sys.argv[sys.argv.index("--port") + 1])
print("Total VRAM 8188 MB, total RAM 32000 MB")
print("WARNING: finto avviso")
time.sleep(float(os.environ.get("RITARDO_FINTO", "0.3")))
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if not self.path.startswith("/system_stats"):
            self.send_response(404); self.end_headers(); return
        corpo = json.dumps({"system": {"comfyui_version": "0.9.9", "argv": [os.path.abspath(__file__)] + sys.argv[1:]},
                            "devices": [{"name": "cuda:0 finta", "vram_total": 1, "vram_free": 1}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(corpo)
    def log_message(self, *a):
        pass
print("To see the GUI go to: http://127.0.0.1:%d" % porta, flush=True)
HTTPServer(("127.0.0.1", porta), H).serve_forever()
'''


def porta_libera() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def con_venv(c: Path) -> Path:
    """Un finto venv di ComfyUI che punta al Python dei test."""
    cartella = c / "venv" / ("Scripts" if os.name == "nt" else "bin")
    cartella.mkdir(parents=True)
    py = cartella / ("python.exe" if os.name == "nt" else "python")
    try:
        py.symlink_to(sys.executable)
    except OSError:
        import shutil
        shutil.copy(sys.executable, py)
    return py


def prepara(casa, tmp_path, main=MAIN_FINTO, **imp):
    c = crea_cartella_comfy(tmp_path)
    (c / "main.py").write_text(main, encoding="utf-8")
    con_venv(c)
    porta = porta_libera()
    archivio = Archivio(casa / "impostazioni.json")
    archivio.aggiorna(comfy_dir=str(c.resolve()), comfy_url=f"http://127.0.0.1:{porta}", **imp)
    return c, porta, App(archivio)


def attendi(c, id_, limite=30):
    for _ in range(int(limite / 0.1)):
        l = next(x for x in c.get("/api/lavori").json() if x["id"] == id_)
        if l["stato"] not in ("in_coda", "in_corso"):
            return l
        time.sleep(0.1)
    raise AssertionError("il lavoro non finisce")


# ---------------------------------------------------------------- comandi

def test_comando_portable(tmp_path):
    radice = tmp_path / "ComfyUI_windows_portable"
    c = crea_cartella_comfy(radice)
    emb = radice / "python_embeded"
    emb.mkdir()
    (emb / ("python.exe" if os.name == "nt" else "python")).write_text("")
    cmd = avvio.comando(str(c), str(c), "portable", "http://127.0.0.1:8190", extra="--lowvram")
    assert cmd.argomenti[1:] == ["-s", str(c / "main.py"), "--windows-standalone-build", "--port", "8190",
                                 "--lowvram"]
    assert cmd.cartella == radice and cmd.porta == 8190


def test_comando_manuale_usa_il_venv(tmp_path):
    c = crea_cartella_comfy(tmp_path)
    py = con_venv(c)
    cmd = avvio.comando(str(c), None, "manuale", None)
    assert cmd.argomenti == [str(py), "main.py", "--port", "8188"] and cmd.cartella == c


def test_comando_personalizzato_e_desktop(tmp_path, monkeypatch):
    cmd = avvio.comando(None, None, "sconosciuto", "http://127.0.0.1:9000", personalizzato="run.sh --x",
                        extra="--cpu")
    assert cmd.argomenti == ["run.sh", "--x", "--cpu"] and cmd.porta == 9000
    monkeypatch.setattr(avvio, "eseguibile_desktop", lambda: None)
    with pytest.raises(avvio.ErroreAvvio, match="Desktop"):
        avvio.comando(str(tmp_path), None, "desktop", None)
    monkeypatch.setattr(avvio, "eseguibile_desktop", lambda: ["ComfyUI.exe"])
    d = avvio.comando(str(tmp_path), None, "desktop", None)
    assert d.app_desktop and d.porta == 8000


def test_lettore_log_e_spiegazioni(tmp_path):
    f = tmp_path / "comfyui.log"
    f.write_bytes(b"vecchio\n")
    lettore = avvio.LettoreLog(f)
    with open(f, "ab") as o:
        o.write(b"uno\r\ndue\nmet")
    assert lettore.nuove() == ["uno", "due"]
    with open(f, "ab") as o:
        o.write(b"a\n")
    assert lettore.nuove() == ["meta"]
    assert "torchsde" in avvio.spiega_errore(["ModuleNotFoundError: No module named 'torchsde'"], 8188)
    assert "8188" in avvio.spiega_errore(["OSError: [Errno 98] address already in use"], 8188)
    assert avvio.livello_riga("Traceback (most recent call last):") == "errore"
    assert avvio.livello_riga("WARNING: x") == "avviso"


# ---------------------------------------------------------------- avvio vero e proprio

def test_avvia_segue_il_registro_e_ferma(casa, tmp_path):
    _, porta, stato = prepara(casa, tmp_path)
    with TestClient(crea_app(stato, sorveglia=False)) as c:
        l = attendi(c, c.post("/api/comfy/avvia").json()["id"])
        assert l["stato"] == "completato", l
        s = c.get("/api/comfy/stato").json()
        assert s["connesso"] and s["avviato_da_noi"] and s["pid"]
        pid = s["pid"]
        time.sleep(0.8)
        log = [e["msg"] for e in c.get("/api/log").json()]
        assert any(m.startswith("ComfyUI › To see the GUI") for m in log)
        assert (casa / "comfyui.pid").exists()

        l = attendi(c, c.post("/api/comfy/ferma").json()["id"])
        assert l["stato"] == "completato"
        assert not avvio.vivo(pid)
        s = c.get("/api/comfy/stato").json()
        assert not s["connesso"] and not s["avviato_da_noi"]
        assert c.post("/api/comfy/ferma").status_code == 409


def test_avvio_automatico_all_apertura(casa, tmp_path):
    _, porta, stato = prepara(casa, tmp_path)
    with TestClient(crea_app(stato, sorveglia=True)) as c:
        for _ in range(200):
            if c.get("/api/sistema").json()["comfy"]["connesso"]:
                break
            time.sleep(0.1)
        s = c.get("/api/comfy/stato").json()
        assert s["connesso"] and s["avviato_da_noi"]
        attendi(c, c.post("/api/comfy/ferma").json()["id"])


def test_senza_avvio_automatico_non_parte(casa, tmp_path):
    _, porta, stato = prepara(casa, tmp_path, avvio_automatico=False)
    with TestClient(crea_app(stato, sorveglia=True)) as c:
        time.sleep(1.5)
        assert not any(l["tipo"] == "avvio_comfy" for l in c.get("/api/lavori").json())
        assert not c.get("/api/comfy/stato").json()["connesso"]


def test_se_e_gia_attivo_si_aggancia(casa, finto_comfy, cartella_comfy, monkeypatch):
    monkeypatch.setattr(discovery, "PORTE", [finto_comfy.porta])
    archivio = Archivio(casa / "impostazioni.json")
    archivio.aggiorna(comfy_dir=str(cartella_comfy.resolve()), comfy_url="http://127.0.0.1:1")
    with TestClient(crea_app(App(archivio), sorveglia=False)) as c:
        l = attendi(c, c.post("/api/comfy/avvia").json()["id"])
        assert l["stato"] == "completato"
        s = c.get("/api/comfy/stato").json()
        assert s["connesso"] and s["url"] == finto_comfy.url and not s["avviato_da_noi"]
        assert c.post("/api/comfy/ferma").status_code == 409


def test_errore_chiaro_se_comfy_si_chiude(casa, tmp_path):
    main = "import sys\nprint(\"ModuleNotFoundError: No module named 'torchsde'\", flush=True)\nsys.exit(1)\n"
    _, _, stato = prepara(casa, tmp_path, main=main)
    with TestClient(crea_app(stato, sorveglia=False)) as c:
        l = attendi(c, c.post("/api/comfy/avvia").json()["id"])
        assert l["stato"] == "errore" and "torchsde" in l["errore"]
        assert not c.get("/api/comfy/stato").json()["avviato_da_noi"]


def test_impostazioni_di_avvio(casa):
    with TestClient(crea_app(App(Archivio(casa / "impostazioni.json")), sorveglia=False)) as c:
        r = c.post("/api/comfy/avvio", json={"avvio_automatico": False, "argomenti_comfy": "--lowvram",
                                              "comando_comfy": "  ", "attesa_avvio": 5}).json()
        imp = r["impostazioni"]
        assert imp["avvio_automatico"] is False and imp["argomenti_comfy"] == "--lowvram"
        assert imp["comando_comfy"] is None and imp["attesa_avvio"] == 30
        assert r["avvio_automatico"] is False
