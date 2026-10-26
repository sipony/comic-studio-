"""Il workflow di ogni proposta e di ogni immagine del dataset si salva; si rivede come grafo e si confronta."""
import json

from fastapi.testclient import TestClient

from app.grafo import abbina, confronta
from app.main import crea_app
from app.proposte import ConfigProposte, workflow
from app.settings import Archivio
from app.state import App
from app.workflows import aggiungi_posa, applica, integrato, per_invio
from test_dataset import attendi


def test_abbinamento_per_ruolo_anche_con_nodi_in_mezzo():
    c = ConfigProposte(checkpoint="wai.safetensors", inquadratura="figura_intera", lora_stile="K.safetensors")
    wp, _ = workflow(c, "a, b, white background", "n", 1, None)
    wd, r = integrato("wai.safetensors", "ip", "cv", "K.safetensors", 0.8, 0.7, 0.8, 28, 6.0)
    wd = applica(wd, r, riferimento="x.png", positivo="a, city street, b", negativo="n", seme=2,
                 dimensioni=(1024, 1024), prefisso="ds")
    aggiungi_posa(wd, "op", "s.png")
    coppie = dict(abbina(wp, wd))
    # i prompt si riconoscono da dove arrivano (positivo / negativo del campionatore), anche col ControlNet in mezzo
    assert coppie["2"] == "8" and coppie["3"] == "9" and coppie["10"] == "2" and coppie["7"] == "11"
    d = confronta(wp, wd, "proposta", "dataset", ignora=("seed", "filename_prefix"))
    testi = [x["testo"] for x in d["righe"]]
    assert sum(x["tipo"] == "solo_b" for x in d["righe"]) == 8          # IPAdapter (5) e posa (3)
    assert "KSampler · model: in dataset passa prima per IPAdapterAdvanced, poi arriva da LoraLoader come in proposta" in testi
    t = next(x for x in d["righe"] if x["campo"] == "text")
    assert t["solo_a"] == ["white background"] and t["solo_b"] == ["city street"]
    assert d["evidenzia_a"]["2"] == ["text"] and d["evidenzia_b"]["cs_posa"] == ["*"]
    assert not any(x["tipo"] == "collegamento" for x in d["righe"])
    assert confronta(wp, wp)["uguali"]


def test_grafi_della_proposta_e_del_dataset(casa, finto_comfy, cartella_comfy):
    stato = App(Archivio(casa / "impostazioni.json"))
    with TestClient(crea_app(stato, sorveglia=False)) as c:
        c.post("/api/comfy/usa", json={"url": finto_comfy.url, "cartella": str(cartella_comfy)})
        p = c.post("/api/progetti", json={"nome": "Polizia"}).json()["id"]
        c.post(f"/api/progetti/{p}/personaggi", json={"nome": "Ada", "genere": "1girl",
                                                      "descrizione": "long blonde hair, police uniform"})
        base = f"/api/progetti/{p}/personaggi/ada"
        conf = {"checkpoint": "waiIllustriousSDXL_v170.safetensors", "numero": 2, "inquadratura": "figura_intera",
                "stile": "western comics", "lora_stile": "Comic_Style.safetensors"}
        l = attendi(c, c.post(f"{base}/proposte", json=conf).json()["id"])
        assert l["stato"] == "completato", l["errore"]
        prop = c.get(f"{base}/proposte").json()
        g = c.get(f"{base}/proposte/{prop[0]['file']}/workflow").json()
        assert g["ricostruito"] is False and g["impostazioni"]["campi"] == {}
        assert g["workflow"] == finto_comfy.ricevuti[-2]                 # proprio quello mandato a ComfyUI
        assert {n["classe"] for n in g["grafo"]["nodi"]} >= {"CheckpointLoaderSimple", "LoraLoader", "KSampler"}
        js = c.get(g["url_json"])
        assert "attachment" in js.headers["content-disposition"] and js.json()["7"]["class_type"] == "KSampler"
        # proposta vecchia (senza file del workflow): si ricostruisce identica
        cartella = casa / "progetti" / p / "personaggi" / "ada" / "proposte" / "workflow"
        salvato = json.loads((cartella / prop[0]["file"].replace(".png", ".json")).read_text())
        (cartella / prop[0]["file"].replace(".png", ".json")).unlink()
        g = c.get(f"{base}/proposte/{prop[0]['file']}/workflow").json()
        assert g["ricostruito"] is True and "0.23" in g["nota"] and g["workflow"] == salvato

        c.post(f"{base}/proposte/{prop[0]['file']}/scegli")
        l = attendi(c, c.post(f"{base}/dataset/genera", json={"quantita": 2}).json()["id"])
        assert l["stato"] == "completato", l["errore"]
        imm = c.get(f"{base}/dataset/immagini").json()
        gi = c.get(f"{base}/dataset/immagini/{imm[1]['file']}/workflow").json()
        assert gi["ricostruito"] is False and per_invio(gi["workflow"]) == finto_comfy.ricevuti[-1]
        assert gi["workflow"]["11"]["_meta"]["title"] == "Sampler"           # con i titoli dei nodi

        k = c.get(f"{base}/dataset/immagini/{imm[1]['file']}/confronto").json()
        assert k["file_proposta"] == prop[0]["file"] and k["proposta"]["lavoro"]["tipo"] == "proposta"
        # IPAdapter non installato: stessi nodi; cambiano solo il prompt (parte variabile) e forse le dimensioni
        assert not any(r["tipo"] in ("solo_a", "solo_b", "collegamento") for r in k["righe"]), k["righe"]
        assert {r["campo"] for r in k["righe"]} <= {"text", "width", "height"}
        t = next(r for r in k["righe"] if r["campo"] == "text")
        assert "western comics" not in t["solo_a"] + t["solo_b"]          # lo stile c'è in tutti e due

        # immagine vecchia: ricostruita uguale a quella mandata
        wcart = casa / "progetti" / p / "personaggi" / "ada" / "dataset" / "workflow"
        (wcart / imm[1]["file"].replace(".png", ".json")).unlink()
        gi2 = c.get(f"{base}/dataset/immagini/{imm[1]['file']}/workflow").json()
        assert gi2["ricostruito"] is True and gi2["workflow"] == gi["workflow"]
        # eliminando l'immagine anche il suo workflow va nel cestino
        c.post(f"{base}/dataset/elimina", json={"file": [imm[0]["file"]]})
        assert not (wcart / imm[0]["file"].replace(".png", ".json")).exists()
        assert c.get(f"{base}/dataset/immagini/{imm[0]['file']}/workflow").status_code == 404
