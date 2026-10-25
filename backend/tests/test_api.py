import io
import time

from fastapi.testclient import TestClient
from PIL import Image

from app.main import crea_app
from app.settings import Archivio
from app.state import App


def client(casa, sorveglia=False):
    stato = App(Archivio(casa / "impostazioni.json"))
    return TestClient(crea_app(stato, sorveglia=sorveglia)), stato


def test_flusso_progetto_e_personaggi(casa):
    c, _ = client(casa)
    with c:
        assert c.get("/api/progetti").json() == []
        p = c.post("/api/progetti", json={"nome": "La mappa"}).json()
        assert c.get("/api/sistema").json()["impostazioni"]["ultimo_progetto"] == p["id"]
        r = c.post(f"/api/progetti/{p['id']}/personaggi", json={"nome": "Agente", "trigger": "vglcop"})
        assert r.status_code == 201
        r = c.post(f"/api/progetti/{p['id']}/personaggi", json={"nome": "Bis", "trigger": "vglcop"})
        assert r.status_code == 400 and "già usata" in r.json()["detail"]
        b = io.BytesIO()
        Image.new("RGB", (20, 30)).save(b, "JPEG")
        r = c.put(f"/api/progetti/{p['id']}/personaggi/agente/riferimento",
                  files={"file": ("rif.jpg", b.getvalue(), "image/jpeg")})
        assert r.json()["riferimento"] == "riferimento.png"
        img = c.get(f"/api/progetti/{p['id']}/personaggi/agente/riferimento")
        assert img.headers["content-type"] == "image/png"
        assert c.get("/api/progetti/inesistente").status_code == 404
        assert c.get("/api/trigger/suggerisci", params={"nome": "Commissario"}).json()["trigger"]
        assert c.delete(f"/api/progetti/{p['id']}").status_code == 204
        assert c.get("/api/progetti").json() == []
        assert c.get("/api/niente").status_code == 404


def test_ricerca_e_connessione(casa, finto_comfy, cartella_comfy):
    c, stato = client(casa)
    with c:
        r = c.post("/api/comfy/usa", json={"url": finto_comfy.url, "cartella": str(cartella_comfy.parent)})
        assert r.status_code == 200
        s = r.json()
        assert s["connesso"] and s["gpu"].startswith("cuda:0") and s["cartella"] == str(cartella_comfy.resolve())
        m = c.get("/api/comfy/modelli").json()
        assert m["checkpoints"][0] == "ponyDiffusionV6XL.safetensors"
        r = c.post("/api/comfy/usa", json={"url": finto_comfy.url, "cartella": str(casa)})
        assert r.status_code == 400
        lavoro = c.post("/api/comfy/cerca").json()
        for _ in range(100):
            l = next(x for x in c.get("/api/lavori").json() if x["id"] == lavoro["id"])
            if l["stato"] == "completato":
                break
            time.sleep(0.05)
        assert l["stato"] == "completato"
        assert len(c.get("/api/sistema").json()["installazioni"]) == 1


def test_avvio_trova_e_seleziona_comfy_da_solo(casa, finto_comfy, cartella_comfy, monkeypatch):
    from app.comfy import discovery
    monkeypatch.setattr(discovery, "PORTE", [finto_comfy.porta])
    c, stato = client(casa, sorveglia=True)
    with c:
        for _ in range(100):
            imp = c.get("/api/sistema").json()["impostazioni"]
            if imp["comfy_dir"]:
                break
            time.sleep(0.05)
        assert imp["comfy_dir"] == str(cartella_comfy.resolve()) and imp["comfy_url"] == finto_comfy.url


def test_websocket_riceve_eventi(casa):
    c, stato = client(casa)
    with c:
        with c.websocket_connect("/api/eventi") as ws:
            assert ws.receive_json()["tipo"] == "benvenuto"
            c.post("/api/progetti", json={"nome": "Evento"})
            e = ws.receive_json()
            assert e["tipo"] == "log" and "Evento" in e["msg"]


def test_rifiuta_host_estranei(casa):
    c, _ = client(casa)
    with c:
        assert c.get("/api/progetti", headers={"host": "evil.example.com"}).status_code == 400
        assert c.get("/api/progetti", headers={"host": "127.0.0.1:8765"}).status_code == 200
