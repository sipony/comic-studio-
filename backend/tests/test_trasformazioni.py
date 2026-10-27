"""Trasformazioni: dallo stato A (il personaggio) allo stato B, sequenza di fotogrammi, GIF, personaggio «stato B»."""
import io

from fastapi.testclient import TestClient
from PIL import Image

from app.main import crea_app
from app.settings import Archivio
from app.state import App
from app.trasformazioni import DefinizioneTrasformazione, prompt_b, valori
from test_dataset import attendi

MOSTRO = {"nome": "Il mostro", "tag_b": "monster, body horror, extra eyes, cracked skin", "togli": "handsome",
          "negativo_b": "cute", "lora": "Horror_Style.safetensors", "forza_lora": 0.9, "passi": 4, "inizio": 0.3,
          "fine": 0.9}


def test_prompt_e_valori():
    d = DefinizioneTrasformazione(**MOSTRO)
    assert prompt_b("masterpiece, 1boy, solo, (handsome:1.1), priest, western comics", d) == \
        "masterpiece, 1boy, solo, priest, western comics, monster, body horror, extra eyes, cracked skin"
    assert [valori(d, i) for i in range(4)] == [(0.0, 0.3), (0.3333, 0.5), (0.6667, 0.7), (1.0, 0.9)]


def test_sequenza_e_personaggio_stato_b(casa, finto_comfy, cartella_comfy):
    stato = App(Archivio(casa / "impostazioni.json"))
    with TestClient(crea_app(stato, sorveglia=False)) as c:
        c.post("/api/comfy/usa", json={"url": finto_comfy.url, "cartella": str(cartella_comfy)})
        p = c.post("/api/progetti", json={"nome": "Horror"}).json()["id"]
        c.post(f"/api/progetti/{p}/personaggi", json={"nome": "Padre Anselmo", "genere": "1boy",
                                                      "descrizione": "old man, handsome, priest, black cassock"})
        base = f"/api/progetti/{p}/personaggi/padre_anselmo"
        conf = {"checkpoint": "waiIllustriousSDXL_v170.safetensors", "numero": 1, "inquadratura": "figura_intera",
                "stile": "western comics", "lora_stile": "Comic_Style.safetensors"}
        assert attendi(c, c.post(f"{base}/proposte", json=conf).json()["id"])["stato"] == "completato"
        prop = c.get(f"{base}/proposte").json()[0]
        c.post(f"{base}/proposte/{prop['file']}/scegli")

        r = c.post(f"{base}/trasformazioni", json=MOSTRO | {"inizio": 0.9, "fine": 0.3})
        assert r.status_code == 400
        x = c.post(f"{base}/trasformazioni", json=MOSTRO).json()
        a = c.post(f"{base}/trasformazioni/anteprima", json={"definizione": MOSTRO}).json()
        assert a["prompt_a"] == prop["prompt"] and "handsome" not in a["prompt_b"]
        assert a["prompt_b"].endswith("western comics, monster, body horror, extra eyes, cracked skin")
        assert a["negativo_b"].endswith(", cute") and len(a["fotogrammi"]) == 4

        n0 = len(finto_comfy.ricevuti)
        l = attendi(c, c.post(f"{base}/trasformazioni/{x['id']}/genera", json={}).json()["id"])
        assert l["stato"] == "completato", l["errore"]
        inviati = finto_comfy.ricevuti[n0:]
        assert len(inviati) == 4
        semi = {w["13"]["inputs"]["seed"] for w in inviati}
        assert len(semi) == 1                                              # stesso seme per tutti
        assert [w["8"]["inputs"]["conditioning_to_strength"] for w in inviati] == [0.0, 0.3333, 0.6667, 1.0]
        assert [w["13"]["inputs"]["denoise"] for w in inviati] == [0.3, 0.5, 0.7, 0.9]
        assert [w["3"]["inputs"]["strength_model"] for w in inviati] == [0.0, 0.3, 0.6, 0.9]
        assert inviati[0]["3"]["inputs"]["model"] == ["2", 0]              # dopo la LoRA di stile
        assert inviati[0]["4"]["inputs"]["text"] == prop["prompt"]
        assert inviati[0]["10"]["inputs"]["image"].endswith("_stato_a.png")
        el = c.get(f"{base}/trasformazioni").json()[0]
        assert [f["file"] for f in el["fotogrammi"]] == ["01.png", "02.png", "03.png", "04.png"]
        assert el["seme"] in semi
        assert c.get(f"{base}/trasformazioni/{x['id']}/fotogrammi/02.png").status_code == 200
        g = c.get(f"{base}/trasformazioni/{x['id']}/fotogrammi/04.png/workflow").json()
        assert any(n["classe"] == "ConditioningAverage" for n in g["grafo"]["nodi"])
        gi = c.get(f"{base}/trasformazioni/{x['id']}/gif")
        im = Image.open(io.BytesIO(gi.content))
        assert gi.headers["content-type"] == "image/gif" and im.n_frames == 6          # A → B → A

        # rigenerare con lo stesso seme / un seme nuovo
        n0 = len(finto_comfy.ricevuti)
        attendi(c, c.post(f"{base}/trasformazioni/{x['id']}/genera", json={"nuovo_seme": True}).json()["id"])
        assert finto_comfy.ricevuti[n0]["13"]["inputs"]["seed"] not in semi

        # lo stato B diventa un personaggio a sé, pronto per il suo dataset
        r = c.post(f"{base}/trasformazioni/{x['id']}/personaggio", json={"fotogramma": "04.png"}).json()
        nuovo = r["personaggio"]
        assert nuovo["nome"] == "Padre Anselmo (Il mostro)" and nuovo["riferimento"]
        assert nuovo["descrizione"] == "old man, priest, black cassock, monster, body horror, extra eyes, cracked skin"
        assert nuovo["origine"]["positivo"].endswith("monster, body horror, extra eyes, cracked skin")
        assert r["avviso"] and "Horror_Style" in r["avviso"]               # c'era già la LoRA di stile
        ds = c.get(f"/api/progetti/{p}/personaggi/{nuovo['id']}/dataset").json()
        assert "monster" in ds["config"]["prompt_positivo"]

        c.delete(f"{base}/trasformazioni/{x['id']}")
        assert c.get(f"{base}/trasformazioni").json() == []
