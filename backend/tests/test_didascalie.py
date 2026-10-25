import io
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import rotte_didascalie
from app.dataset import ArchivioDataset, InfoImmagine
from app.didascalie import ArchivioDidascalie, ConfigDidascalie, Tagger, componi, normalizza_tag
from app.main import crea_app
from app.projects import Archivio, NuovoPersonaggio, Personaggio
from app.settings import Archivio as ArchivioImpostazioni
from app.state import App


def png(colore, w=64, h=96):
    b = io.BytesIO()
    Image.new("RGB", (w, h), colore).save(b, "PNG")
    return b.getvalue()


def crea_tagger(cartella):
    """Tagger finto con le stesse firme di WD14: ingresso NHWC 448 in BGR, una probabilità per tag."""
    onnx = pytest.importorskip("onnx")
    from onnx import TensorProto, helper
    k = helper.make_tensor("k", TensorProto.FLOAT, [1], [255.0])
    nodi = [helper.make_node("ReduceMean", ["input_1:0"], ["m"], axes=[1, 2], keepdims=0),
            helper.make_node("Div", ["m", "k"], ["predictions_sigmoid"])]
    g = helper.make_graph(nodi, "finto_wd14",
                          [helper.make_tensor_value_info("input_1:0", TensorProto.FLOAT, ["n", 448, 448, 3])],
                          [helper.make_tensor_value_info("predictions_sigmoid", TensorProto.FLOAT, ["n", 3])],
                          initializer=[k])
    m = helper.make_model(g, opset_imports=[helper.make_opsetid("", 13)])
    m.ir_version = 8
    onnx.save(m, cartella / "model.onnx")
    # in BGR: indice 0 = blu, 1 = verde, 2 = rosso
    (cartella / "selected_tags.csv").write_text(
        "tag_id,name,category,count\n1,blue_hair,0,10\n2,green_background,0,10\n3,general,9,10\n")
    return Tagger(cartella / "model.onnx", cartella / "selected_tags.csv")


def test_normalizza():
    assert normalizza_tag(" Blonde_Hair ") == "blonde hair"
    assert normalizza_tag("^_^") == "^_^"


def test_tagger_onnx(tmp_path):
    t = crea_tagger(tmp_path)
    assert t.lato == 448
    for nome, c in [("blu.png", (0, 40, 230)), ("verde.png", (10, 220, 10))]:
        (tmp_path / nome).write_bytes(png(c))
    r = t.tagga([tmp_path / "blu.png", tmp_path / "verde.png"])
    # l'immagine è messa su un quadrato bianco: il colore pesa per 64/96 della larghezza
    assert "blue hair" in r["blu.png"] and "general" not in r["blu.png"]
    assert r["verde.png"]["green background"] > r["blu.png"].get("green background", 0)


def pers(**kw):
    d = dict(id="agente", nome="Agente", trigger="vglcop", genere="1girl", descrizione="long blonde hair, blue police uniform")
    d.update(kw)
    return Personaggio(**d)


def test_composizione():
    info = InfoImmagine(file="0001.png", numero=1, variante="upper body, front view, smile, white background")
    grezzi = {"1girl": 0.99, "solo": 0.98, "long blonde hair": 0.9, "smile": 0.8, "necktie": 0.6, "badge": 0.3}
    c = ConfigDidascalie(rimossi=["white background"], aggiunti=["police"], sostituzioni={"necktie": "black necktie"},
                         tag_stile="western comics (style)")
    testo = componi(pers(), info, grezzi, c)
    parti = testo.split(", ")
    assert parti[:4] == ["vglcop", "1girl", "solo", "police"]
    assert "long blonde hair" not in parti                    # tratto fisso
    assert "white background" not in parti and "badge" not in parti   # rimosso / sotto soglia
    assert "black necktie" in parti and parti[-1] == "western comics (style)"
    assert parti.count("smile") == 1                          # tagger + prompt senza doppioni
    solo_prompt = componi(pers(), info, None, ConfigDidascalie(modalita="tagger"))
    assert "front view" in solo_prompt                        # senza tag del tagger si usa il prompt
    corto = componi(pers(), info, grezzi, ConfigDidascalie(massimo_tag=5))
    assert len(corto.split(", ")) == 5


@pytest.fixture
def archivio(tmp_path):
    progetti = Archivio(tmp_path / "progetti")
    p = progetti.crea("Prova")
    progetti.aggiungi_personaggio(p.id, NuovoPersonaggio(nome="Agente", trigger="vglcop",
                                                          descrizione="long blonde hair, blue police uniform"))
    ds = ArchivioDataset(progetti)
    for n, stato in [(1, "tenuta"), (2, "tenuta"), (3, "scartata"), (4, None)]:
        ds.aggiungi_immagine(p.id, "agente", png((n * 40, 50, 200)),
                             InfoImmagine(file=f"{n:04d}.png", numero=n, variante=f"upper body, smile, pose{n}", stato=stato))
    return ArchivioDidascalie(ds), p.id


def test_stato_frequenze_e_suggerimenti(archivio):
    a, pid = archivio
    a.salva_tag(pid, "agente", {"0001.png": {"blue eyes": 0.9, "long blonde hair": 0.95, "smile": 0.7},
                                "0002.png": {"blue eyes": 0.8, "long blonde hair": 0.9}})
    s = a.stato(pid, "agente")
    assert s["totale"] == 2 and s["da_selezione"] and s["analizzate"] == 2
    f = {x["tag"]: x for x in s["frequenze"]}
    assert f["blue eyes"]["quota"] == 1.0 and f["blue eyes"]["suggerito"]          # aspetto in ogni immagine
    assert f["long blonde hair"]["rimosso"] and f["long blonde hair"]["fisso"]
    assert not f["smile"]["suggerito"]
    c = ConfigDidascalie(rimossi=["blue eyes"])
    a.salva_config(pid, "agente", c)
    s = a.stato(pid, "agente")
    assert all("blue eyes" not in i["testo"] for i in s["immagini"])
    assert {x["tag"]: x for x in s["frequenze"]}["blue eyes"]["rimosso"]


def test_manuali_esporta_zip(archivio, tmp_path):
    a, pid = archivio
    a.imposta_manuale(pid, "agente", "0002.png", "vglcop, 1girl,  running\n, running ")
    finali = dict((i.file, t) for i, t in a.didascalie_finali(pid, "agente"))
    assert finali["0002.png"] == "vglcop, 1girl, running"
    assert finali["0001.png"].startswith("vglcop, 1girl, solo, upper body")
    dest = tmp_path / "addestramento"
    assert a.esporta(pid, "agente", dest) == 2
    assert sorted(p.name for p in dest.iterdir()) == ["0001.png", "0001.txt", "0002.png", "0002.txt"]
    z = zipfile.ZipFile(io.BytesIO(a.zip(pid, "agente")))
    assert sorted(z.namelist()) == ["0001.png", "0001.txt", "0002.png", "0002.txt"]
    a.imposta_manuale(pid, "agente", "0002.png", None)
    assert not a.stato(pid, "agente")["immagini"][1]["manuale"]


def test_senza_selezione_usa_le_non_scartate(archivio):
    a, pid = archivio
    for f in ("0001.png", "0002.png"):
        a.dataset.imposta_stato(pid, "agente", f, None)
    imm, da_selezione = a.immagini(pid, "agente")
    assert not da_selezione and [i.file for i in imm] == ["0001.png", "0002.png", "0004.png"]


def test_api_didascalie(casa, tmp_path, monkeypatch):
    tagger = crea_tagger(tmp_path)
    monkeypatch.setattr(rotte_didascalie, "carica_tagger", lambda *a, **k: tagger)
    stato = App(ArchivioImpostazioni(casa / "impostazioni.json"))
    c = TestClient(crea_app(stato, sorveglia=False))
    with c:
        p = c.post("/api/progetti", json={"nome": "Prova"}).json()["id"]
        c.post(f"/api/progetti/{p}/personaggi", json={"nome": "Agente", "trigger": "vglcop"})
        base = f"/api/progetti/{p}/personaggi/agente/didascalie"
        r = c.post(f"{base}/analizza", json={})
        assert r.status_code == 400
        ds = ArchivioDataset(stato.progetti)
        for n in (1, 2):
            ds.aggiungi_immagine(p, "agente", png((0, 30, 230)), InfoImmagine(file=f"{n:04d}.png", numero=n,
                                                                               variante="full body", stato="tenuta"))
        lid = c.post(f"{base}/analizza", json={}).json()["id"]
        for _ in range(200):
            l = next(x for x in c.get("/api/lavori").json() if x["id"] == lid)
            if l["stato"] not in ("in_coda", "in_corso"):
                break
        assert l["stato"] == "completato", l["errore"]
        s = c.get(base).json()
        assert s["analizzate"] == 2 and "blue hair" in s["immagini"][0]["testo"]
        cfg = s["config"]
        cfg["rimossi"] = ["blue hair"]
        s = c.put(f"{base}/config", json=cfg).json()
        assert "blue hair" not in s["immagini"][0]["testo"]
        assert c.put(f"{base}/immagini/0001.png", json={"testo": "vglcop, 1girl, a mano"}).status_code == 200
        assert c.put(f"{base}/immagini/9999.png", json={"testo": "x"}).status_code == 404
        s = c.get(base).json()
        assert s["immagini"][0]["manuale"] and s["immagini"][0]["testo"] == "vglcop, 1girl, a mano"
        z = c.get(f"{base}/zip")
        assert z.headers["content-type"] == "application/zip" and "vglcop" in z.headers["content-disposition"]
        assert len(zipfile.ZipFile(io.BytesIO(z.content)).namelist()) == 4
