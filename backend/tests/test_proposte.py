"""Personaggio dal nulla: dal testo alle proposte d'immagine di riferimento."""
import time

from fastapi.testclient import TestClient

from app.main import crea_app
from app.settings import Archivio
from app.state import App


def attendi(c, lid):
    for _ in range(500):
        l = next(x for x in c.get("/api/lavori").json() if x["id"] == lid)
        if l["stato"] not in ("in_coda", "in_corso"):
            return l
        time.sleep(0.02)
    raise AssertionError("il lavoro non finisce")


def test_personaggio_dal_testo(casa, finto_comfy, cartella_comfy, finto_ollama):
    archivio = Archivio(casa / "impostazioni.json")
    archivio.aggiorna(ia_url=finto_ollama.url, ia_libera_gpu=False)
    stato = App(archivio)
    with TestClient(crea_app(stato, sorveglia=False)) as c:
        c.post("/api/comfy/usa", json={"url": finto_comfy.url, "cartella": str(cartella_comfy)})
        p = c.post("/api/progetti", json={"nome": "Horror"}).json()["id"]
        c.post(f"/api/progetti/{p}/personaggi", json={"nome": "Mara", "storia": "Mara ha trent'anni, capelli ramati..."})
        base = f"/api/progetti/{p}/personaggi/mara/proposte"
        assert c.get(base).json() == []
        conf = {"checkpoint": "waiIllustriousSDXL_v150.safetensors", "numero": 2, "stile": "western comics (style)"}
        l = attendi(c, c.post(base, json=conf).json()["id"])
        assert l["stato"] == "completato", l["errore"]
        # i tratti li ha ricavati l'IA e sono stati salvati nel personaggio
        pers = c.get(f"/api/progetti/{p}").json()["personaggi"][0]
        assert "auburn" in pers["descrizione"] and pers["adulto"] is True
        proposte = c.get(base).json()
        assert len(proposte) == 2 and proposte[0]["seme"] != proposte[1]["seme"]
        inviato = finto_comfy.ricevuti[-1]
        testi = [n["inputs"]["text"] for n in inviato.values() if n["class_type"] == "CLIPTextEncode"]
        assert testi[0].startswith("masterpiece, best quality, amazing quality, 1girl, solo")
        assert "long wavy auburn hair" in testi[0] and "white background" in testi[0] and "cowboy shot" in testi[0]
        assert any(n["class_type"] == "EmptyLatentImage" for n in inviato.values())
        assert c.get(f"{base}/{proposte[0]['file']}").status_code == 200

        # scelta → immagine di riferimento
        r = c.post(f"{base}/{proposte[1]['file']}/scegli").json()
        assert r["riferimento"] == "riferimento.png"
        assert c.get(f"/api/progetti/{p}/personaggi/mara/riferimento").status_code == 200
        assert [x["scelta"] for x in c.get(base).json()] == [False, True]

        # varianti della proposta scelta (img2img)
        l = attendi(c, c.post(base, json=conf | {"numero": 1, "da": proposte[1]["file"]}).json()["id"])
        assert l["stato"] == "completato", l["errore"]
        inviato = finto_comfy.ricevuti[-1]
        assert any(n["class_type"] == "LoadImage" for n in inviato.values())
        assert next(n for n in inviato.values() if n["class_type"] == "KSampler")["inputs"]["denoise"] == 0.55
        assert c.get(base).json()[-1]["da"] == proposte[1]["file"]

        # le non scelte vanno nel cestino
        assert c.post(f"{base}/scarta").json() == {"spostate_nel_cestino": 2}
        assert [x["file"] for x in c.get(base).json()] == [proposte[1]["file"]]
        assert list((stato.progetti.radice / ".cestino").glob("*proposte*"))


def test_proposte_bloccate_e_senza_testo(casa, finto_comfy, cartella_comfy):
    stato = App(Archivio(casa / "impostazioni.json"))
    with TestClient(crea_app(stato, sorveglia=False)) as c:
        c.post("/api/comfy/usa", json={"url": finto_comfy.url, "cartella": str(cartella_comfy)})
        p = c.post("/api/progetti", json={"nome": "X"}).json()["id"]
        c.post(f"/api/progetti/{p}/personaggi", json={"nome": "Vuoto"})
        r = c.post(f"/api/progetti/{p}/personaggi/vuoto/proposte", json={"checkpoint": "ck0.safetensors"})
        assert r.status_code == 400 and "descrizione" in r.json()["detail"]
        c.post(f"/api/progetti/{p}/personaggi", json={"nome": "Altro", "storia": "una bambina di 10 anni, nuda"})
        r = c.post(f"/api/progetti/{p}/personaggi/altro/proposte", json={"checkpoint": "ck0.safetensors"})
        assert r.status_code == 422
