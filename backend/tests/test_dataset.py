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


# ---------------------------------------------------------------- img2img: pose e inquadrature diverse

def wf_img2img(lora=True, campionatore="KSampler"):
    """Come «Cala_Maranello_img2img»: il KSampler parte dall'immagine di riferimento codificata dal VAE."""
    wf = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "waiIllustriousSDXL_v170.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": "1girl", "clip": ["1", 1]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": "lowres", "clip": ["1", 1]}},
        "20": {"class_type": "LoadImage", "inputs": {"image": "rif.png"}},
        "21": {"class_type": "ImageScale", "inputs": {"image": ["20", 0], "width": 832, "height": 1216,
                                                       "upscale_method": "lanczos", "crop": "center"}},
        "22": {"class_type": "VAEEncode", "inputs": {"pixels": ["21", 0], "vae": ["1", 2]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["1", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "x"}},
    }
    modello, clip = ["1", 0], ["1", 1]
    if lora:
        wf["2"] = {"class_type": "LoraLoader", "inputs": {"model": modello, "clip": clip, "strength_model": 0.8,
                                                         "strength_clip": 0.8, "lora_name": "Maranello_ViperRSR.safetensors"}}
        modello = ["2", 0]
    if campionatore == "KSampler":
        wf["7"] = {"class_type": "KSampler", "inputs": {"model": modello, "positive": ["4", 0], "negative": ["5", 0],
                                                        "latent_image": ["22", 0], "seed": 1, "steps": 28, "cfg": 6,
                                                        "sampler_name": "euler", "scheduler": "karras", "denoise": 0.55}}
    else:
        wf["7"] = {"class_type": "KSamplerAdvanced", "inputs": {"model": modello, "positive": ["4", 0],
                                                                "negative": ["5", 0], "latent_image": ["22", 0],
                                                                "noise_seed": 1, "add_noise": "disable",
                                                                "start_at_step": 12, "end_at_step": 10000}}
    return wf


def test_img2img_riconosciuto_e_composizione_libera():
    from app.workflows import analizza, applica, guide_identita, img2img, integrato
    wf = wf_img2img()
    a = analizza(wf)
    assert a.ruoli.riferimento == "20" and a.ruoli.latente is None
    assert a.img2img == {"campionatore": "7", "codifica": "22", "denoise": 0.55} and a.guide == []
    assert a.lora == ["Maranello_ViperRSR.safetensors"]

    # composizione libera: latente vuoto della variante, denoise pieno; il workflow salvato non cambia
    w = applica(wf, a.ruoli, riferimento="r.png", dimensioni=(1024, 1024), composizione_libera=True)
    assert w["cs_latente"]["class_type"] == "EmptyLatentImage"
    assert (w["cs_latente"]["inputs"]["width"], w["cs_latente"]["inputs"]["height"]) == (1024, 1024)
    assert w["7"]["inputs"]["latent_image"] == ["cs_latente", 0] and w["7"]["inputs"]["denoise"] == 1.0
    assert wf["7"]["inputs"]["latent_image"] == ["22", 0] and "cs_latente" not in wf
    # composizione del riferimento: img2img come prima
    w = applica(wf, a.ruoli, riferimento="r.png", dimensioni=(1024, 1024), composizione_libera=False)
    assert "cs_latente" not in w and w["7"]["inputs"]["denoise"] == 0.55
    # Flux / SD3 usano il loro latente
    w = applica(wf, a.ruoli, dimensioni=(832, 1216), composizione_libera=True, classe_latente="EmptySD3LatentImage")
    assert w["cs_latente"]["class_type"] == "EmptySD3LatentImage"

    # KSamplerAdvanced: si parte dal primo passo, con il rumore
    adv = wf_img2img(campionatore="KSamplerAdvanced")
    w = applica(adv, analizza(adv).ruoli, dimensioni=(832, 1216), composizione_libera=True)
    assert w["7"]["inputs"]["start_at_step"] == 0 and w["7"]["inputs"]["add_noise"] == "enable"

    # il workflow integrato (IPAdapter + latente vuoto) non è img2img e ha una guida dell'aspetto
    integ, ruoli = integrato("ck.safetensors", "ip.safetensors", "cv.safetensors")
    assert img2img(integ, ruoli.riferimento) is None and guide_identita(integ, ruoli.riferimento)
    w = applica(integ, ruoli, dimensioni=(832, 1216), composizione_libera=True)
    assert "cs_latente" not in w

    # un secondo passaggio (hires fix) che ricodifica l'uscita del primo non è img2img
    due = wf_img2img()
    due["7"]["inputs"]["latent_image"] = ["30", 0]
    due["30"] = {"class_type": "EmptyLatentImage", "inputs": {"width": 832, "height": 1216, "batch_size": 1}}
    due["31"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["8", 0], "vae": ["1", 2]}}
    due["32"] = {"class_type": "KSampler", "inputs": {**due["7"]["inputs"], "latent_image": ["31", 0]}}
    assert img2img(due, "20") is None


def test_generazione_img2img_con_pose_diverse(ambiente):
    import json
    c, p, stato, finto = ambiente
    base = f"/api/progetti/{p}"
    c.put(f"{base}/personaggi/agente/riferimento", files={"file": ("r.png", png((250, 220, 90)), "image/png")})
    r = c.post(f"{base}/workflows", files={"file": ("img2img.json", json.dumps(wf_img2img()).encode(), "application/json")})
    assert r.status_code == 201, r.text
    wid = r.json()["id"]
    assert c.get(f"{base}/workflows/{wid}").json()["analisi"]["img2img"]["denoise"] == 0.55
    cfg = c.get(f"{base}/personaggi/agente/dataset").json()["config"]
    assert cfg["composizione"] == "libera"
    cfg["workflow"] = wid
    c.put(f"{base}/personaggi/agente/dataset/config", json=cfg)
    l = attendi(c, c.post(f"{base}/personaggi/agente/dataset/genera", json={"quantita": 4}).json()["id"])
    assert l["stato"] == "completato", l["errore"]
    inviati = finto.ricevuti[-4:]
    # ogni immagine parte da un latente vuoto delle dimensioni della sua inquadratura, con il prompt della variante
    assert all(w["7"]["inputs"]["latent_image"] == ["cs_latente", 0] and w["7"]["inputs"]["denoise"] == 1.0
               for w in inviati)
    imm = c.get(f"{base}/personaggi/agente/dataset/immagini").json()
    for w, i in zip(inviati, imm):
        assert (w["cs_latente"]["inputs"]["width"], w["cs_latente"]["inputs"]["height"]) == (i["larghezza"], i["altezza"])
        assert w["4"]["inputs"]["text"] == i["prompt"]
    assert len({i["inquadratura"] for i in imm}) == 4
    assert any("ogni immagine parte da zero" in r["msg"] for r in c.get("/api/log").json())

    # chi vuole la composizione del riferimento la può tenere
    cfg["composizione"] = "riferimento"
    c.put(f"{base}/personaggi/agente/dataset/config", json=cfg)
    attendi(c, c.post(f"{base}/personaggi/agente/dataset/genera", json={"quantita": 1}).json()["id"])
    assert finto.ricevuti[-1]["7"]["inputs"]["latent_image"] == ["22", 0]


# ---------------------------------------------------------------- scaricare, eliminare, liberare spazio

def test_scarica_zip_elimina_e_libera_spazio(ambiente):
    import zipfile
    c, p, stato, finto = ambiente
    base = f"/api/progetti/{p}/personaggi/agente/dataset"
    a = rotte_dataset.ArchivioDataset(stato.progetti)
    from app.dataset import InfoImmagine
    for k in range(1, 6):
        a.aggiungi_immagine(p, "agente", png((k * 40, 10, 10), 200, 300),
                            InfoImmagine(file=f"{k:04d}.png", numero=k, prompt=f"prompt {k}"))
    rie = c.get(base).json()["riepilogo"]
    assert rie["totale"] == 5 and rie["byte"] > 0 and rie["cestino"] == {"immagini": 0, "byte": 0}

    # ZIP di tre immagini, con i prompt e i metadati
    l = attendi(c, c.post(f"{base}/esporta", json={"file": ["0001.png", "0002.png", "0003.png"]}).json()["id"])
    assert l["stato"] == "completato", l["errore"]
    r = stato.gestore.lavori[l["id"]].risultato
    assert r["immagini"] == 3 and r["file"] == ["0001.png", "0002.png", "0003.png"]
    z = c.get(f"{base}/esportazioni/{r['nome']}")
    assert z.status_code == 200 and z.headers["content-type"] == "application/zip"
    assert r["nome"] in z.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(z.content)) as zz:
        assert sorted(zz.namelist()) == ["agente/0001.png", "agente/0001.txt", "agente/0002.png", "agente/0002.txt",
                                         "agente/0003.png", "agente/0003.txt", "agente/immagini.json"]
        assert zz.read("agente/0002.txt") == b"prompt 2"
    # dopo il download lo ZIP non resta sul disco
    assert c.get(f"{base}/esportazioni/{r['nome']}").status_code == 404
    assert c.get(f"{base}/esportazioni/..%2F..%2Fx.zip").status_code == 404

    # scaricate: cancellate davvero dal disco, senza passare dal cestino
    cartella = a.cartella(p, "agente")
    d = c.post(f"{base}/elimina", json={"file": r["file"], "definitivo": True}).json()
    assert d["eliminate"] == 3 and d["liberati"] > 0
    assert not (cartella / "generate" / "0001.png").exists() and not (cartella / "anteprime" / "0001.jpg").exists()
    assert c.get(base).json()["riepilogo"]["cestino"]["immagini"] == 0

    # elimina tutte: nel cestino, poi lo svuoto per liberare lo spazio
    assert c.post(f"{base}/elimina", json={}).json()["eliminate"] == 2
    rie = c.get(base).json()["riepilogo"]
    assert rie["totale"] == 0 and rie["byte"] == 0 and rie["cestino"]["immagini"] == 2
    # il cestino di un altro personaggio non si tocca
    altro = stato.progetti.radice / ".cestino" / f"{p}-altro-dataset-1"
    altro.mkdir(parents=True)
    (altro / "0001.png").write_bytes(b"x")
    s = c.post(f"{base}/cestino/svuota").json()
    assert s["immagini"] == 2 and s["byte"] > 0
    assert c.get(f"{base}/cestino").json() == {"immagini": 0, "byte": 0} and altro.exists()
    assert c.post(f"{base}/esporta", json={}).status_code == 200      # il lavoro fallisce: nessuna immagine
