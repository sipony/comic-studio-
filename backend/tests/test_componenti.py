"""IPAdapter Plus installato da Comic Studio: cosa manca, spazio su disco, download controllati, nodo dallo ZIP."""
import dataclasses
import hashlib
import io
import threading
import time
import zipfile
from collections import namedtuple

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.responses import RedirectResponse, Response
from fastapi.testclient import TestClient

from app import componenti as comp
from app.main import crea_app
from app.settings import Archivio
from app.state import App
from finto_comfy import _porta_libera
from test_testo_prompt import attendi

IP = b"I" * 300_000
CLIP = b"C" * 700_000


def zip_nodo() -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("ComfyUI_IPAdapter_plus-main/__init__.py", "NODE_CLASS_MAPPINGS = {}\n")
        z.writestr("ComfyUI_IPAdapter_plus-main/IPAdapterPlus.py", "# finto\n")
    return b.getvalue()


class FintoDownload:
    """Hugging Face (con il rimando e lo SHA-256 in x-linked-etag) e lo ZIP di GitHub."""

    def __init__(self):
        self.app = FastAPI()
        self.rovina = False
        self.richieste: list[str] = []
        app = self.app

        @app.get("/hf/{nome}")
        async def risolvi(nome: str):
            self.richieste.append(nome)
            dati = IP if nome == "ip.safetensors" else CLIP
            return RedirectResponse(f"/cdn/{nome}", status_code=302,
                                    headers={"x-linked-etag": f'"{hashlib.sha256(dati).hexdigest()}"',
                                             "x-linked-size": str(len(dati))})

        @app.get("/cdn/{nome}")
        async def cdn(nome: str):
            dati = IP if nome == "ip.safetensors" else CLIP
            if self.rovina:
                dati = b"X" + dati[1:]
            return Response(dati, media_type="application/octet-stream")

        @app.get("/gh/main.zip")
        async def gh():
            return Response(zip_nodo(), media_type="application/zip")

        self.porta = _porta_libera()
        self.url = f"http://127.0.0.1:{self.porta}"
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.porta, log_level="error"))
        threading.Thread(target=self.server.run, daemon=True).start()
        for _ in range(100):
            if self.server.started:
                break
            time.sleep(0.05)

    def ferma(self):
        self.server.should_exit = True


@pytest.fixture
def download(monkeypatch):
    f = FintoDownload()
    nodo, ip, clip = comp.IPADAPTER
    monkeypatch.setattr(comp, "IPADAPTER", [
        dataclasses.replace(nodo, url=f"{f.url}/gh/main.zip"),
        dataclasses.replace(ip, url=f"{f.url}/hf/ip.safetensors", byte=len(IP)),
        dataclasses.replace(clip, url=f"{f.url}/hf/clip.safetensors", byte=len(CLIP)),
    ])
    monkeypatch.setattr(comp.shutil, "which", lambda nome: None)     # senza git: si usa lo ZIP
    yield f
    f.ferma()


def prepara(casa, cartella_comfy):
    a = Archivio(casa / "impostazioni.json")
    a.aggiorna(comfy_dir=str(cartella_comfy), avvio_automatico=False, ia_avvio_automatico=False)
    stato = App(a)
    return stato, TestClient(crea_app(stato, sorveglia=False))


def test_cosa_manca_anche_con_altri_nomi(tmp_path):
    base = tmp_path / "ComfyUI"
    (base / "custom_nodes").mkdir(parents=True)
    s = comp.controlla(str(base))
    assert [m["id"] for m in s.mancanti] == ["nodo_ipadapter", "modello_ipadapter", "clip_vision_vit_h"]
    assert s.totale == sum(c.byte for c in comp.IPADAPTER) and s.basta_spazio is not None
    # già presenti con altri nomi, o in cartelle che vede solo ComfyUI (extra_model_paths)
    (base / "custom_nodes" / "comfyui_ipadapter_plus").mkdir()
    (base / "models" / "ipadapter" / "sdxl").mkdir(parents=True)
    (base / "models" / "ipadapter" / "sdxl" / "ip-adapter-plus_sdxl_vit-h.bin").write_bytes(b"x")
    s = comp.controlla(str(base), modelli={"clip_vision": ["altro/CLIP-ViT-H-14.safetensors"]})
    assert not s.mancanti and s.totale == 0
    # il nodo sul disco ma ComfyUI non lo carica: non si reinstalla, si segnala
    s = comp.controlla(str(base), modelli={"clip_vision": ["CLIP-ViT-H-14.safetensors"]}, nodi_caricati={"KSampler"})
    assert not s.mancanti and s.da_caricare == ["nodo_ipadapter"]
    assert comp.controlla(None).errore and comp.controlla(str(tmp_path / "no")).errore


def test_spazio_insufficiente(casa, cartella_comfy, download, monkeypatch):
    Uso = namedtuple("Uso", "total used free")
    monkeypatch.setattr(comp.shutil, "disk_usage", lambda p: Uso(100 * comp.GB, 99.5 * comp.GB, int(0.5 * comp.GB)))
    stato, c = prepara(casa, cartella_comfy)
    with c:
        s = c.get("/api/componenti").json()
        assert not s["basta_spazio"] and s["chiedi"]
        assert "servono 1,0 GB" in s["messaggio_spazio"] and "liberi 0,5" in s["messaggio_spazio"]
        assert s["spazio"][0]["cartella"] == str(cartella_comfy)
        r = c.post("/api/componenti/installa")
        assert r.status_code == 409 and "libera" in r.json()["detail"]
        assert not download.richieste


def test_installazione_completa(casa, cartella_comfy, download):
    stato, c = prepara(casa, cartella_comfy)
    with c:
        s = c.get("/api/componenti").json()
        assert len(s["mancanti"]) == 3 and s["basta_spazio"] and stato.componenti == s
        l = attendi(c, c.post("/api/componenti/installa").json()["id"])
        assert l["stato"] == "completato", l["errore"]
        assert (cartella_comfy / "custom_nodes" / "ComfyUI_IPAdapter_plus" / "__init__.py").exists()
        assert (cartella_comfy / "models" / "ipadapter" / "ip-adapter-plus_sdxl_vit-h.safetensors").read_bytes() == IP
        assert (cartella_comfy / "models" / "clip_vision" / "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"
                ).read_bytes() == CLIP
        assert not list(cartella_comfy.rglob("*.parziale"))
        s = c.get("/api/componenti").json()
        assert not s["mancanti"] and s["totale"] == 0
        assert c.post("/api/componenti/installa").status_code == 400
        # e il dataset «come le proposte» ora li trova (ComfyUI spento: dal disco)
        modelli = c.get("/api/comfy/modelli").json()
        assert "ip-adapter-plus_sdxl_vit-h.safetensors" in modelli["ipadapter"]
        assert "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors" in modelli["clip_vision"]
        # «non chiedere più»
        assert c.post("/api/componenti/chiedi", json={"chiedi": False}).json()["chiedi"] is False
        assert stato.impostazioni.valori.chiedi_componenti is False


def test_download_rovinato_non_lascia_file(casa, cartella_comfy, download):
    download.rovina = True
    stato, c = prepara(casa, cartella_comfy)
    with c:
        l = attendi(c, c.post("/api/componenti/installa").json()["id"])
        assert l["stato"] == "errore" and "rovinato" in l["errore"]
        assert not (cartella_comfy / "models" / "ipadapter" / "ip-adapter-plus_sdxl_vit-h.safetensors").exists()
        assert not list(cartella_comfy.rglob("*.parziale"))
        # il nodo (già installato prima dell'errore) resta; riprovando si scaricano solo i modelli
        download.rovina = False
        s = c.get("/api/componenti").json()
        assert [m["id"] for m in s["mancanti"]] == ["modello_ipadapter", "clip_vision_vit_h"]
        assert attendi(c, c.post("/api/componenti/installa").json()["id"])["stato"] == "completato"


def test_installazione_controlnet_delle_pose(casa, cartella_comfy, download, monkeypatch):
    """Il gruppo «pose» (ControlNet OpenPose) si installa a parte e non tocca la richiesta di IPAdapter all'apertura."""
    (cn,) = comp.POSE
    monkeypatch.setattr(comp, "POSE", [dataclasses.replace(cn, url=f"{download.url}/hf/clip.safetensors",
                                                           byte=len(CLIP))])
    stato, c = prepara(casa, cartella_comfy)
    with c:
        prima = c.get("/api/componenti").json()
        s = c.get("/api/componenti?gruppo=pose").json()
        assert [m["id"] for m in s["mancanti"]] == ["controlnet_openpose"] and s["gruppo"] == "pose"
        assert stato.componenti == prima                    # lo stato di IPAdapter (finestra all'apertura) non cambia
        l = attendi(c, c.post("/api/componenti/installa?gruppo=pose").json()["id"])
        assert l["stato"] == "completato", l["errore"] and l["titolo"] == "Installazione di ControlNet OpenPose"
        f = cartella_comfy / "models" / "controlnet" / "controlnet-openpose-sdxl-1.0-xinsir.safetensors"
        assert f.read_bytes() == CLIP
        assert c.get("/api/componenti?gruppo=pose").json()["mancanti"] == []
        assert len(c.get("/api/componenti").json()["mancanti"]) == 3      # IPAdapter ancora da installare
        r = c.post("/api/componenti/installa?gruppo=pose")
        assert r.status_code == 400 and "ControlNet OpenPose è già installato" in r.json()["detail"]
        assert "controlnet-openpose-sdxl-1.0-xinsir.safetensors" in c.get("/api/comfy/modelli").json()["controlnet"]
