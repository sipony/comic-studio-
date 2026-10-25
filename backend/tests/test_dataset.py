import io
import random
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import rotte_dataset
from app.dataset import ConfigDataset, componi, crea_variante, varianti_predefinite
from app.main import crea_app
from app.settings import Archivio
from app.somiglianza import ValutatoreSemplice, prepara, scegli
from app.state import App


def png(colore=(10, 20, 30), w=64, h=96):
    b = io.BytesIO()
    Image.new("RGB", (w, h), colore).save(b, "PNG")
    return b.getvalue()


def test_componi_pulisce_le_virgole():
    assert componi("{qualita}, {genere}, solo, {descrizione}, {variante}",
                   {"qualita": "", "genere": "1girl", "descrizione": "", "variante": "upper body, smile"}) \
        == "1girl, solo, upper body, smile"
    assert componi("{sconosciuto}, x", {}) == "{sconosciuto}, x"


def test_varianti_rispettano_le_quote():
    v = varianti_predefinite()
    conteggio, rng = {}, random.Random(1)
    uscite = [crea_variante(v, conteggio, rng) for _ in range(100)]
    assert conteggio == {"primo piano": 25, "mezzo busto": 30, "tre quarti": 20, "figura intera": 25}
    primi = [u for u in uscite if u["_nome_inquadratura"] == "primo piano"]
    assert all("behind" not in u["variante"] and u["posa"] == "" for u in primi)
    assert {u["_dimensioni"] for u in primi} == {"1024x1024"}


def test_scegli_quote_doppioni_e_scelte_manuali():
    rng = np.random.default_rng(0)
    E = rng.normal(size=(10, 8)).astype(np.float32)
    E[1] = E[0]                                              # doppione
    E /= np.linalg.norm(E, axis=1, keepdims=True)
    punteggi = [0.9, 0.89, 0.5, 0.6, 0.7, 0.4, 0.3, 0.8, 0.2, 0.1]
    gruppi = ["a", "a", "a", "a", "a", "b", "b", "b", "b", "b"]
    s = scegli(punteggi, E, gruppi, 4, {"a": 1, "b": 1})
    assert 0 in s and 1 not in s and len(s) == 4
    assert sum(gruppi[i] == "b" for i in s) == 2
    s = scegli(punteggi, E, gruppi, 3, None, forzati={9}, esclusi={0})
    assert 9 in s and 0 not in s


def test_valutatore_semplice_e_preparazione(tmp_path):
    for i, c in enumerate([(200, 0, 0), (205, 5, 5), (0, 0, 200)]):
        (tmp_path / f"{i}.png").write_bytes(png(c))
    E = ValutatoreSemplice().vettori(sorted(tmp_path.glob("*.png")))
    assert E.shape[0] == 3 and float(E[0] @ E[1]) > float(E[0] @ E[2])
    assert prepara(Image.new("RGB", (300, 500))).shape == (3, 224, 224)


# ---------------------------------------------------------------- flusso completo via API

@pytest.fixture
def ambiente(casa, finto_comfy, cartella_comfy, monkeypatch):
    monkeypatch.setattr(rotte_dataset, "valutatore", lambda *a, **k: ValutatoreSemplice())
    stato = App(Archivio(casa / "impostazioni.json"))
    c = TestClient(crea_app(stato, sorveglia=False))
    with c:
        c.post("/api/comfy/usa", json={"url": finto_comfy.url, "cartella": str(cartella_comfy)})
        p = c.post("/api/progetti", json={"nome": "Prova"}).json()["id"]
        c.post(f"/api/progetti/{p}/personaggi", json={"nome": "Agente", "trigger": "vglcop", "genere": "1girl",
                                                       "descrizione": "blonde hair, police uniform"})
        yield c, p, stato, finto_comfy


def attendi(c, lid):
    for _ in range(400):
        l = next(x for x in c.get("/api/lavori").json() if x["id"] == lid)
        if l["stato"] not in ("in_coda", "in_corso"):
            return l
        time.sleep(0.02)
    raise AssertionError("lavoro bloccato")


def test_flusso_dataset(ambiente):
    c, p, stato, finto = ambiente
    base = f"/api/progetti/{p}"
    wf = c.post(f"{base}/workflows/integrato", json={"checkpoint": "ponyDiffusionV6XL.safetensors",
                                                    "ipadapter": "ip.safetensors", "clip_vision": "cv.safetensors"}).json()
    assert wf["ruoli"]["riferimento"] == "5" and wf["checkpoint"] == "ponyDiffusionV6XL.safetensors"

    cfg = c.get(f"{base}/personaggi/agente/dataset").json()["config"]
    cfg["workflow"] = wf["id"]
    cfg["modifiche"] = {"11": {"steps": 12}}
    assert c.put(f"{base}/personaggi/agente/dataset/config", json=cfg).status_code == 200

    esempi = c.post(f"{base}/personaggi/agente/dataset/esempi", json=cfg).json()
    assert esempi[0]["positivo"].startswith("score_9")          # tag di qualità di Pony
    assert "blonde hair" in esempi[0]["positivo"]

    # senza riferimento non parte
    r = c.post(f"{base}/personaggi/agente/dataset/genera", json={"quantita": 3})
    assert r.status_code == 400 and "riferimento" in r.json()["detail"]
    c.put(f"{base}/personaggi/agente/riferimento", files={"file": ("r.png", png((250, 220, 90)), "image/png")})

    l = c.post(f"{base}/personaggi/agente/dataset/genera", json={"quantita": 4}).json()
    l = attendi(c, l["id"])
    assert l["stato"] == "completato", l["errore"]
    imm = c.get(f"{base}/personaggi/agente/dataset/immagini").json()
    assert [i["file"] for i in imm] == ["0001.png", "0002.png", "0003.png", "0004.png"]
    inviato = finto.ricevuti[-1]
    assert inviato["11"]["inputs"]["steps"] == 12
    assert inviato["5"]["inputs"]["image"].endswith("_riferimento.png")
    assert inviato["8"]["inputs"]["text"] == imm[-1]["prompt"]
    assert c.get(f"{base}/personaggi/agente/dataset/immagini/0001.png?anteprima=true").headers["content-type"] == "image/jpeg"

    # scelta manuale + selezione automatica
    c.patch(f"{base}/personaggi/agente/dataset/immagini/0004.png", json={"stato": "scartata"})
    l = attendi(c, c.post(f"{base}/personaggi/agente/dataset/seleziona", json={"quante": 2}).json()["id"])
    assert l["stato"] == "completato", l["errore"]
    imm = {i["file"]: i for i in c.get(f"{base}/personaggi/agente/dataset/immagini").json()}
    assert imm["0004.png"]["stato"] == "scartata" and imm["0004.png"]["manuale"]
    assert sum(i["stato"] == "tenuta" for i in imm.values()) == 2
    assert all(i["punteggio"] is not None for i in imm.values())
    assert c.get(f"{base}/personaggi/agente/dataset").json()["riepilogo"]["tenute"] == 2

    # aggiunta: la numerazione continua; poi pulizia delle scartate
    attendi(c, c.post(f"{base}/personaggi/agente/dataset/genera", json={"quantita": 1}).json()["id"])
    assert c.get(f"{base}/personaggi/agente/dataset/immagini").json()[-1]["file"] == "0005.png"
    n = c.post(f"{base}/personaggi/agente/dataset/elimina", json={"scartate": True}).json()["eliminate"]
    assert n == 2
    assert len(c.get(f"{base}/personaggi/agente/dataset/immagini").json()) == 3


def test_caricamento_workflow_e_ruoli(ambiente):
    c, p, *_ = ambiente
    base = f"/api/progetti/{p}"
    dati = (rotte_dataset.Path(__file__).parent / "dati" / "workflow_api_4_vignette.json").read_bytes()
    r = c.post(f"{base}/workflows", files={"file": ("quattro.json", dati, "application/json")})
    assert r.status_code == 201, r.text
    w = r.json()
    assert w["nome"] == "quattro" and w["nodi"] == 29
    d = c.get(f"{base}/workflows/{w['id']}").json()
    assert d["analisi"]["ruoli"]["riferimento"] == "2"
    r = c.patch(f"{base}/workflows/{w['id']}", json={"ruoli": {**w["ruoli"], "positivo": "11"}})
    assert r.status_code == 400 and "testo" in r.json()["detail"]
    r = c.patch(f"{base}/workflows/{w['id']}", json={"ruoli": {**w["ruoli"], "positivo": "20"}, "nome": "Quattro vignette"})
    assert r.json()["ruoli"]["positivo"] == "20" and r.json()["nome"] == "Quattro vignette"
    r = c.post(f"{base}/workflows", files={"file": ("rotto.json", b"{non json", "application/json")})
    assert r.status_code == 400
    assert c.delete(f"{base}/workflows/{w['id']}").status_code == 204
    assert c.get(f"{base}/workflows").json() == []


def test_config_non_valida(ambiente):
    c, p, *_ = ambiente
    cfg = ConfigDataset().model_dump()
    cfg["varianti"]["inquadrature"] = []
    r = c.put(f"/api/progetti/{p}/personaggi/agente/dataset/config", json=cfg)
    assert r.status_code == 400
    cfg = ConfigDataset(workflow="inesistente").model_dump()
    assert c.put(f"/api/progetti/{p}/personaggi/agente/dataset/config", json=cfg).status_code == 404


def test_valutatore_clip_con_modello_onnx(tmp_path):
    onnx = pytest.importorskip("onnx")
    from onnx import TensorProto, helper

    from app.somiglianza import ValutatoreClip
    nodi = [helper.make_node("GlobalAveragePool", ["pixel_values"], ["m"]),
            helper.make_node("Flatten", ["m"], ["image_embeds"])]
    g = helper.make_graph(nodi, "finto_clip",
                          [helper.make_tensor_value_info("pixel_values", TensorProto.FLOAT, ["n", 3, 224, 224])],
                          [helper.make_tensor_value_info("image_embeds", TensorProto.FLOAT, ["n", 3])])
    m = helper.make_model(g, opset_imports=[helper.make_opsetid("", 13)])
    m.ir_version = 8
    onnx.save(m, tmp_path / "clip.onnx")
    for i, c in enumerate([(220, 10, 10), (230, 20, 15), (10, 10, 220)]):
        (tmp_path / f"{i}.png").write_bytes(png(c))
    v = ValutatoreClip(tmp_path / "clip.onnx")
    E = v.vettori(sorted(tmp_path.glob("*.png")))
    assert E.shape == (3, 3)
    assert np.allclose(np.linalg.norm(E, axis=1), 1, atol=1e-5)
    assert float(E[0] @ E[1]) > float(E[0] @ E[2])


def test_caricamento_formato_interfaccia(ambiente):
    import json

    from test_workflows import OBJECT_INFO, workflow_ui
    c, p, stato, finto = ambiente
    finto.object_info = OBJECT_INFO
    r = c.post(f"/api/progetti/{p}/workflows",
               files={"file": ("mio.json", json.dumps(workflow_ui()).encode(), "application/json")})
    assert r.status_code == 201, r.text
    w = r.json()
    assert w["nodi"] == 7 and w["ruoli"]["positivo"] == "6" and w["ruoli"]["negativo"] == "7"
    assert w["ruoli"]["riferimento"] is None and any("LoadImage" in a for a in w["avvisi"])
    r = c.get(f"/api/comfy/nodi", params={"classi": "KSampler,Inesistente"}).json()
    assert list(r) == ["KSampler"] and "seed" in r["KSampler"]["input"]["required"]
