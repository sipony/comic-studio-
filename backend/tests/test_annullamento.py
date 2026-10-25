"""Annullamento in qualsiasi momento, con le risorse liberate; anteprime durante la generazione."""
import asyncio
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient

from app.comfy.client import ComfyClient, leggi_anteprima
from app.jobs import Bus, Gestore
from app.main import crea_app
from app.settings import Archivio
from app.state import App

WF = {
    "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "a.safetensors"}},
    "2": {"class_type": "KSampler", "inputs": {}},
    "3": {"class_type": "SaveImage", "inputs": {}},
}


def test_annullare_toglie_dalla_coda_interrompe_e_libera_la_vram(finto_comfy):
    finto_comfy.lento = 0.3

    async def prova():
        async with ComfyClient(finto_comfy.url) as a, ComfyClient(finto_comfy.url) as b:
            ta = asyncio.create_task(a.esegui(WF))
            await asyncio.sleep(0.25)                      # A è in esecuzione
            tb = asyncio.create_task(b.esegui(WF))
            await asyncio.sleep(0.2)                       # B è in coda dietro ad A
            assert finto_comfy.in_corso and len(finto_comfy.coda) == 1
            tb.cancel()
            with pytest.raises(asyncio.CancelledError):
                await tb
            assert len(finto_comfy.cancellati) == 1 and finto_comfy.interruzioni == 0   # A non si tocca
            assert finto_comfy.liberazioni == 1
            ta.cancel()
            with pytest.raises(asyncio.CancelledError):
                await ta
            assert finto_comfy.interruzioni == 1 and finto_comfy.liberazioni == 2
            await asyncio.sleep(0.4)
            assert finto_comfy.in_corso is None and not finto_comfy.coda
    asyncio.run(prova())


def test_anteprime_durante_il_campionamento(finto_comfy):
    finto_comfy.anteprime = True
    viste = []

    async def prova():
        async with ComfyClient(finto_comfy.url) as c:
            await c.esegui(WF, anteprima=lambda dati, tipo: viste.append((tipo, dati[:2])))
    asyncio.run(prova())
    assert len(viste) == 4 and viste[0] == ("image/jpeg", b"\xff\xd8")
    meta = b'{"image_type": "image/png"}'
    assert leggi_anteprima((4).to_bytes(4, "big") + len(meta).to_bytes(4, "big") + meta + b"png") == (b"png", "image/png")
    assert leggi_anteprima(b"\x00\x00\x00\x09xxxxyy") is None


def test_interrotto_da_comfyui_spiegato(finto_comfy):
    finto_comfy.lento = 0.2

    async def prova():
        async with ComfyClient(finto_comfy.url) as c:
            t = asyncio.create_task(c.esegui(WF))
            await asyncio.sleep(0.2)
            await c.interrompi()
            with pytest.raises(Exception, match="interrotta in ComfyUI"):
                await t
    asyncio.run(prova())


def test_annullare_un_lavoro_in_attesa_della_gpu():
    async def prova():
        g = Gestore(Bus())
        primo = g.avvia("a", "Primo", lambda l: asyncio.sleep(0.3), esclusivo=True)
        secondo = g.avvia("b", "Secondo", lambda l: asyncio.sleep(0.01), esclusivo=True)
        await asyncio.sleep(0.05)
        assert secondo.stato == "in_coda"
        assert g.annulla(secondo.id) and g.annulla(secondo.id)       # il secondo clic non fa danni
        await asyncio.sleep(0.05)
        assert secondo.stato == "annullato"
        await asyncio.sleep(0.35)
        assert primo.stato == "completato"
        terzo = g.avvia("c", "Terzo", lambda l: asyncio.sleep(0.01), esclusivo=True)   # la GPU è di nuovo libera
        await asyncio.sleep(0.1)
        assert terzo.stato == "completato"
        quarto = g.avvia("d", "Quarto", lambda l: asyncio.sleep(5))
        quinto = g.avvia("e", "Quinto", lambda l: asyncio.sleep(5))
        await asyncio.sleep(0.02)
        assert g.annulla_tutti() == 2
        await asyncio.sleep(0.05)
        assert quarto.stato == quinto.stato == "annullato"
    asyncio.run(prova())


def test_kohya_annullato_aspetta_che_il_processo_esca():
    from app.rotte_addestramento import _termina
    from app.comfy.avvio import vivo
    p = subprocess.Popen([sys.executable, "-c", "import subprocess, sys, time; "
                          "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); time.sleep(60)"])
    time.sleep(0.5)
    import psutil
    figli = [c.pid for c in psutil.Process(p.pid).children(recursive=True)]
    _termina(p.pid)
    p.wait(timeout=5)
    assert not vivo(p.pid) and figli and not any(vivo(f) for f in figli)


def test_annullare_una_generazione_dall_api_con_anteprima(casa, finto_comfy, cartella_comfy):
    finto_comfy.lento = 0.25
    finto_comfy.anteprime = True
    stato = App(Archivio(casa / "impostazioni.json"))
    with TestClient(crea_app(stato, sorveglia=False)) as c:
        c.post("/api/comfy/usa", json={"url": finto_comfy.url, "cartella": str(cartella_comfy)})
        p = c.post("/api/progetti", json={"nome": "X"}).json()["id"]
        c.post(f"/api/progetti/{p}/personaggi", json={"nome": "Mara", "descrizione": "red hair"})
        base = f"/api/progetti/{p}/personaggi/mara/proposte"
        lid = c.post(base, json={"checkpoint": "ck0.safetensors", "numero": 4}).json()["id"]
        for _ in range(100):
            l = next(x for x in c.get("/api/lavori").json() if x["id"] == lid)
            if l["anteprima"]:
                break
            time.sleep(0.05)
        r = c.get(f"/api/lavori/{lid}/anteprima")
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
        assert c.post(f"/api/lavori/{lid}/annulla").status_code == 200
        for _ in range(100):
            l = next(x for x in c.get("/api/lavori").json() if x["id"] == lid)
            if l["stato"] not in ("in_coda", "in_corso"):
                break
            time.sleep(0.05)
        assert l["stato"] == "annullato"
        assert finto_comfy.interruzioni == 1 and finto_comfy.liberazioni >= 1
        assert len(c.get(base).json()) < 4
        log = [x["msg"] for x in c.get("/api/log").json()]
        assert any("memoria della GPU liberata" in m for m in log)
        # la GPU è libera: un nuovo lavoro parte subito
        finto_comfy.lento = 0
        lid = c.post(base, json={"checkpoint": "ck0.safetensors", "numero": 1}).json()["id"]
        for _ in range(100):
            l = next(x for x in c.get("/api/lavori").json() if x["id"] == lid)
            if l["stato"] not in ("in_coda", "in_corso"):
                break
            time.sleep(0.05)
        assert l["stato"] == "completato"


def test_annullare_la_domanda_all_ia_scarica_il_modello(casa, finto_ollama):
    finto_ollama.lento = 2.0
    archivio = Archivio(casa / "impostazioni.json")
    archivio.aggiorna(ia_url=finto_ollama.url, ia_libera_gpu=False)
    stato = App(archivio)
    with TestClient(crea_app(stato, sorveglia=False)) as c:
        lid = c.post("/api/ia/prova", json={"testo": "una scena"}).json()["id"]
        time.sleep(0.4)
        c.post(f"/api/lavori/{lid}/annulla")
        for _ in range(100):
            if next(x for x in c.get("/api/lavori").json() if x["id"] == lid)["stato"] == "annullato":
                break
            time.sleep(0.05)
        assert finto_ollama.scaricati == ["qwen3:8b"]
