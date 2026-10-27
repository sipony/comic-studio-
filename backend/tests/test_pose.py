"""Pose guidate: libreria degli scheletri OpenPose, ControlNet aggiunto al workflow, generazione del dataset."""
import io

import numpy as np

from PIL import Image

from app import pose
from app.workflows import NODI_POSA, aggiungi_posa, integrato
from test_dataset import ambiente, attendi, png  # noqa: F401 - fixture


# ---------------------------------------------------------------- libreria

def test_pose_destra_sinistra_e_specchiate():
    for p in pose.elenco(con_specchiate=True):
        pt = pose.punti(p)
        assert len(pt) == 18 and pt[pose.COLLO] and pt[pose.ANCA_D] and pt[pose.CAVIGLIA_S]
    davanti = pose.punti(pose.trova("in-piedi"))
    # di fronte la destra del personaggio è a sinistra nell'immagine; il naso e gli occhi si vedono
    assert davanti[pose.SPALLA_D][0] < davanti[pose.SPALLA_S][0] and davanti[pose.NASO]
    dietro = pose.punti(pose.trova("di-spalle"))
    assert dietro[pose.SPALLA_D][0] > dietro[pose.SPALLA_S][0]
    assert dietro[pose.NASO] is None and dietro[pose.OCCHIO_D] is None and dietro[pose.ORECCHIO_D]
    # profilo verso destra: si vede l'orecchio destro, non il sinistro
    profilo = pose.punti(pose.trova("profilo"))
    assert profilo[pose.ORECCHIO_D] and profilo[pose.ORECCHIO_S] is None and profilo[pose.NASO][0] > 0
    # il saluto alza la mano destra sopra la testa; specchiato è la sinistra, dall'altra parte
    saluto = pose.punti(pose.trova("saluto"))
    assert saluto[pose.POLSO_D][1] < saluto[pose.NASO][1] and saluto[pose.POLSO_D][0] < 0
    spec = pose.punti(pose.trova("saluto-specchiata"))
    assert spec[pose.POLSO_S][1] < spec[pose.NASO][1] and spec[pose.POLSO_S][0] > 0
    assert pose.trova("saluto-specchiata").nome == "Saluta con la mano (specchiata)"


def colori_di(img) -> set:
    return {tuple(int(x) for x in c) for c in np.unique(np.asarray(img).reshape(-1, 3), axis=0)}


def test_disegno_e_tagli():
    img = pose.disegna(pose.trova("in-piedi"), 832, 1216)
    assert img.size == (832, 1216)
    colori = colori_di(img)
    assert (0, 0, 0) in colori and (255, 0, 0) in colori        # fondo nero, il naso rosso come in OpenPose
    # figura intera: tutto dentro; primo piano: la testa grande e le caviglie fuori
    viola = (85, 0, 255)                                          # caviglia sinistra
    assert viola in colori_di(pose.disegna(pose.trova("in-piedi"), 1024, 1024, "intera"))
    assert viola not in colori_di(pose.disegna(pose.trova("in-piedi"), 1024, 1024, "primo_piano"))
    assert pose.taglio("portrait, close-up, face focus") == "primo_piano"
    assert pose.taglio("upper body") == "mezzo_busto"
    assert pose.taglio("cowboy shot") == "tre_quarti"
    assert pose.taglio("full body") == "intera"
    dati = pose.png(pose.trova("corsa"), 416, 608)
    assert Image.open(io.BytesIO(dati)).size == (416, 608)


def test_rotazione_usa_tutte_le_pose():
    scelte = [pose.trova(i) for i in ("in-piedi", "di-spalle", "saluto")]
    r = pose.Rotazione(scelte)
    usate = [r.prossima("intera").id for _ in range(6)]
    assert usate == ["in-piedi", "di-spalle", "saluto"] * 2
    # nei primi piani niente pose di spalle
    assert {r.prossima("primo_piano").id for _ in range(4)} == {"in-piedi", "saluto"}


# ---------------------------------------------------------------- workflow

def test_controlnet_aggiunto_al_workflow():
    wf, ruoli = integrato("pony.safetensors", "ip.safetensors", "cv.safetensors")
    nodi = aggiungi_posa(wf, "openpose.safetensors", "pose/scheletro.png", 0.7, 0.0, 0.6)
    assert nodi == [NODI_POSA["carica"], NODI_POSA["immagine"], NODI_POSA["applica"]]
    ap = wf[NODI_POSA["applica"]]
    assert ap["class_type"] == "ControlNetApplyAdvanced"
    assert ap["inputs"]["positive"] == ["8", 0] and ap["inputs"]["negative"] == ["9", 0]
    assert ap["inputs"]["strength"] == 0.7 and ap["inputs"]["end_percent"] == 0.6
    assert wf["11"]["inputs"]["positive"] == [NODI_POSA["applica"], 0]
    assert wf["11"]["inputs"]["negative"] == [NODI_POSA["applica"], 1]
    assert wf["11"]["inputs"]["model"] == ["7", 0]                 # IPAdapter resta sul modello
    assert wf[NODI_POSA["immagine"]]["inputs"]["image"] == "pose/scheletro.png"
    # hires fix: anche il secondo campionatore con gli stessi prompt passa per la posa
    wf2, _ = integrato("pony.safetensors", None, None)
    wf2["20"] = {"class_type": "KSampler", "inputs": {**wf2["11"]["inputs"], "latent_image": ["11", 0],
                                                      "denoise": 0.5}}
    aggiungi_posa(wf2, "openpose.safetensors", "s.png")
    assert wf2["20"]["inputs"]["positive"] == [NODI_POSA["applica"], 0]


# ---------------------------------------------------------------- API e dataset

def test_dataset_con_pose_guidate(ambiente):
    c, p, stato, finto = ambiente
    base = f"/api/progetti/{p}"
    elenco = c.get("/api/pose").json()
    assert len(elenco["pose"]) == 2 * len(pose.POSE) and elenco["pose"][1]["id"] == "in-piedi-specchiata"
    r = c.get("/api/pose/saluto/scheletro?larghezza=208&altezza=304&taglio=mezzo_busto")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(r.content)).size == (208, 304)
    assert c.get("/api/pose/nessuna/scheletro").status_code == 404

    wf = c.post(f"{base}/workflows/integrato", json={"checkpoint": "ponyDiffusionV6XL.safetensors",
                                                    "ipadapter": "ip.safetensors", "clip_vision": "cv.safetensors"}).json()
    c.put(f"{base}/personaggi/agente/riferimento", files={"file": ("r.png", png((250, 220, 90)), "image/png")})
    cfg = c.get(f"{base}/personaggi/agente/dataset").json()["config"]
    assert cfg["pose"]["attive"] is False and cfg["pose"]["forza"] == 0.8
    cfg["workflow"] = wf["id"]
    cfg["pose"] = {"attive": True, "pose": ["di-spalle", "saluto", "seduta"], "specchiate": False, "forza": 0.75,
                   "fine": 0.7}
    assert c.put(f"{base}/personaggi/agente/dataset/config", json=cfg).status_code == 200

    # senza ControlNet OpenPose non parte e dice come installarlo
    r = c.post(f"{base}/personaggi/agente/dataset/genera", json={"quantita": 2})
    assert r.status_code == 400 and "ControlNet OpenPose" in r.json()["detail"]
    comp = c.get("/api/componenti?gruppo=pose").json()
    assert [m["id"] for m in comp["mancanti"]] == ["controlnet_openpose"] and comp["nome"] == "ControlNet OpenPose"
    assert c.get("/api/componenti?gruppo=altro").status_code == 422

    finto.modelli["controlnet"] = ["control_v11p_sd15_openpose.pth", "controlnet-openpose-sdxl-1.0.safetensors"]
    assert c.get("/api/componenti?gruppo=pose").json()["mancanti"] == []

    esempi = c.post(f"{base}/personaggi/agente/dataset/esempi", json=cfg).json()
    assert all(e["posa"] in ("di-spalle", "saluto", "seduta") for e in esempi)

    n0 = len(finto.ricevuti)
    l = attendi(c, c.post(f"{base}/personaggi/agente/dataset/genera", json={"quantita": 6}).json()["id"])
    assert l["stato"] == "completato", l["errore"]
    inviati = finto.ricevuti[n0:]
    imm = c.get(f"{base}/personaggi/agente/dataset/immagini").json()
    assert len(inviati) == len(imm) == 6
    for w, i in zip(inviati, imm):
        assert w[NODI_POSA["carica"]]["inputs"]["control_net_name"] == "controlnet-openpose-sdxl-1.0.safetensors"
        assert w[NODI_POSA["applica"]]["inputs"]["strength"] == 0.75
        assert w["11"]["inputs"]["positive"] == [NODI_POSA["applica"], 0]
        posa = pose.trova(i["posa"])
        assert posa.tag in i["prompt"] and posa.vista in i["prompt"] and w["8"]["inputs"]["text"] == i["prompt"]
        sch = w[NODI_POSA["immagine"]]["inputs"]["image"]
        assert f"_posa_{posa.id}_{i['larghezza']}x{i['altezza']}_" in sch
    # nei primi piani niente pose di spalle
    assert not any(i["posa"] == "di-spalle" and i["inquadratura"] == "primo piano" for i in imm)
    assert {i["posa"] for i in imm} == {"di-spalle", "saluto", "seduta"}
    assert any("Pose guidate con controlnet-openpose-sdxl-1.0" in r["msg"] for r in c.get("/api/log").json())

    # una immagine per posa: figura intera, nell'ordine, con le specchiate
    cfg["pose"]["specchiate"] = True
    cfg["pose"]["pose"] = ["saluto", "corsa"]
    c.put(f"{base}/personaggi/agente/dataset/config", json=cfg)
    n0 = len(finto.ricevuti)
    l = attendi(c, c.post(f"{base}/personaggi/agente/dataset/genera",
                          json={"quantita": 1, "una_per_posa": True}).json()["id"])
    assert l["stato"] == "completato", l["errore"]
    assert l["titolo"].endswith("una immagine per posa (4)")
    nuove = c.get(f"{base}/personaggi/agente/dataset/immagini").json()[6:]
    assert [i["posa"] for i in nuove] == ["saluto", "saluto-specchiata", "corsa", "corsa-specchiata"]
    assert all(i["inquadratura"] == "figura intera" and "full body" in i["prompt"] for i in nuove)
    assert len(finto.ricevuti) - n0 == 4

    # il grafo della console dice dove si cambiano i nodi della posa
    lav = c.get(f"/api/lavori/{l['id']}/workflow").json()
    campi = lav["impostazioni"]["campi"]
    assert "Pose guidate" in campi[NODI_POSA["applica"]]["strength"]["perche"]
    assert campi["11"]["steps"]["modificabile"]


def test_stessa_persona_come_le_proposte(casa, finto_comfy, cartella_comfy, monkeypatch):
    """«Stessa persona, come le proposte»: il dataset nasce come le proposte (stesso workflow senza IPAdapter, prompt
    nello stesso ordine, stessa risoluzione, sfondo bianco), cambiano solo posa, angolazione ed espressione; in più
    l'aspetto del riferimento dal tagger."""
    from fastapi.testclient import TestClient
    from app import rotte_dataset
    from app.main import crea_app
    from app.settings import Archivio
    from app.state import App

    class TaggerFinto:
        def tagga(self, immagini, *a, **k):
            return {immagini[0].name: {"1girl": 0.99, "blonde hair": 0.9, "necktie": 0.8, "blue pants": 0.7,
                                       "latex": 0.5, "white background": 0.95, "standing": 0.9, "smile": 0.6,
                                       "police uniform": 0.8, "armband": 0.4, "hand on hip": 0.6}}
    monkeypatch.setattr(rotte_dataset, "carica_tagger", lambda *a, **k: TaggerFinto())
    finto_comfy.modelli |= {"ipadapter": ["ip-adapter-plus_sdxl_vit-h.safetensors"],
                            "clip_vision": ["CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"]}
    stato = App(Archivio(casa / "impostazioni.json"))
    with TestClient(crea_app(stato, sorveglia=False)) as c:
        c.post("/api/comfy/usa", json={"url": finto_comfy.url, "cartella": str(cartella_comfy)})
        p = c.post("/api/progetti", json={"nome": "Polizia"}).json()["id"]
        c.post(f"/api/progetti/{p}/personaggi", json={"nome": "Ada", "genere": "1girl",
                                                      "descrizione": "long blonde hair, police uniform"})
        base = f"/api/progetti/{p}/personaggi/ada"
        assert c.post(f"{base}/dataset/somiglianza").status_code == 400          # senza riferimento
        conf = {"checkpoint": "waiIllustriousSDXL_v170.safetensors", "numero": 1, "inquadratura": "figura_intera",
                "stile": "western comics", "lora_stile": "Comic_Style.safetensors"}
        assert attendi(c, c.post(f"{base}/proposte", json=conf).json()["id"])["stato"] == "completato"
        prop = c.get(f"{base}/proposte").json()[0]
        c.post(f"{base}/proposte/{prop['file']}/scegli")
        cfg = c.get(f"{base}/dataset").json()["config"]
        cfg["pose"]["attive"] = True
        c.put(f"{base}/dataset/config", json=cfg)

        l = attendi(c, c.post(f"{base}/dataset/somiglianza").json()["id"])
        assert l["stato"] == "completato", l["errore"]
        ds = c.get(f"{base}/dataset").json()
        cfg = ds["config"]
        assert cfg["aspetto"] == "necktie, blue pants, latex, armband"
        assert cfg["varianti"]["sfondi"] == ["simple background, white background"]
        assert {(i["larghezza"], i["altezza"]) for i in cfg["varianti"]["inquadrature"]} == {(832, 1216)}
        assert cfg["pose"]["attive"] is False
        wf = c.get(f"/api/progetti/{p}/workflows/{cfg['workflow']}").json()["workflow"]
        ip = [k for k, n in wf.items() if n["class_type"] == "IPAdapterAdvanced"]
        assert ip and cfg["disattivati"] == ip
        # il confronto con la proposta: identico, proprio come le proposte (senza IPAdapter)
        assert ds["origine"]["coerente"], ds["origine"]
        k = c.post(f"{base}/dataset/confronto", json=cfg).json()
        assert k["workflow"]["senza_riferimento"] and k["coerente"]

        # il prompt mandato: ordine delle proposte, il workflow è quello delle proposte
        assert attendi(c, c.post(f"{base}/dataset/genera", json={"quantita": 2}).json()["id"])["stato"] == "completato"
        img = c.get(f"{base}/dataset/immagini").json()[-1]
        assert img["prompt"].startswith("masterpiece, best quality, amazing quality, 1girl, solo, looking at viewer, ")
        assert ", simple background, white background, long blonde hair, police uniform, necktie, blue pants" in img["prompt"]
        assert img["prompt"].endswith("western comics") and (img["larghezza"], img["altezza"]) == (832, 1216)
        g = c.get(f"{base}/dataset/immagini/{img['file']}/confronto").json()
        assert not [r for r in g["righe"] if r["tipo"] in ("solo_a", "solo_b", "collegamento", "passa_per")], g["righe"]
        assert {r["campo"] for r in g["righe"]} <= {"text"}


def _safetensors(f, contesto: int):
    """Un file .safetensors con la sola intestazione di un peso di cross-attention (contesto 768 = SD 1.5, 2048 = SDXL)."""
    import json as _json
    import struct
    intest = _json.dumps({"input_blocks.1.1.transformer_blocks.0.attn2.to_k.weight":
                          {"dtype": "F16", "shape": [320, contesto], "data_offsets": [0, 0]}}).encode()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(struct.pack("<Q", len(intest)) + intest)


def test_controlnet_della_stessa_architettura(ambiente, cartella_comfy):
    """Un ControlNet per SD 1.5 con un checkpoint SDXL fa fallire il KSampler (mat1 and mat2 … 2048 and 768): non si
    sceglie da solo, se scelto a mano si spiega, e l'errore di ComfyUI si traduce."""
    from app.modelinfo import architettura_controlnet
    c, p, stato, finto = ambiente
    base = f"/api/progetti/{p}/personaggi/agente/dataset"
    c.put(f"/api/progetti/{p}/personaggi/agente/riferimento", files={"file": ("r.png", png(), "image/png")})
    wf = c.post(f"/api/progetti/{p}/workflows/integrato", json={"checkpoint": "waiIllustriousSDXL_v170.safetensors",
                                                               "ipadapter": "ip.safetensors",
                                                               "clip_vision": "cv.safetensors"}).json()
    cfg = c.get(base).json()["config"]
    cfg["workflow"] = wf["id"]
    cfg["pose"] = {"attive": True, "pose": ["saluto"], "specchiate": False}
    c.put(f"{base}/config", json=cfg)
    cartella = cartella_comfy / "models" / "controlnet"
    _safetensors(cartella / "openpose_misterioso.safetensors", 768)       # dal nome non si capisce: dal file sì
    _safetensors(cartella / "openpose_buono.safetensors", 2048)
    assert architettura_controlnet("x", cartella / "openpose_misterioso.safetensors") == "sd15"
    assert architettura_controlnet("control_v11p_sd15_openpose.pth") == "sd15"
    assert architettura_controlnet("OpenPoseXL2.safetensors") == "sdxl"

    finto.modelli["controlnet"] = ["control_v11p_sd15_openpose.pth", "openpose_misterioso.safetensors"]
    r = c.post(f"{base}/genera", json={"quantita": 1})
    assert r.status_code == 400 and "altra architettura" in r.json()["detail"]
    d = c.get(f"{base}/controlnet").json()
    assert d["automatico"] is None and d["serve"] == "sdxl"
    assert {x["nome"]: x["compatibile"] for x in d["elenco"]} == {"control_v11p_sd15_openpose.pth": False,
                                                                  "openpose_misterioso.safetensors": False}

    finto.modelli["controlnet"].append("openpose_buono.safetensors")
    assert c.get(f"{base}/controlnet").json()["automatico"] == "openpose_buono.safetensors"
    l = attendi(c, c.post(f"{base}/genera", json={"quantita": 1}).json()["id"])
    assert l["stato"] == "completato", l["errore"]
    assert finto.ricevuti[-1][NODI_POSA["carica"]]["inputs"]["control_net_name"] == "openpose_buono.safetensors"

    # scelto a mano quello sbagliato: non parte e dice perché
    cfg["pose"]["controlnet"] = "control_v11p_sd15_openpose.pth"
    c.put(f"{base}/config", json=cfg)
    r = c.post(f"{base}/genera", json={"quantita": 1})
    assert r.status_code == 400 and "SD 1.5" in r.json()["detail"]

    # l'errore di ComfyUI tradotto
    cfg["pose"]["controlnet"] = None
    c.put(f"{base}/config", json=cfg)
    finto.errore_nodo = "KSampler"
    finto.messaggio_errore = "mat1 and mat2 shapes cannot be multiplied (308x2048 and 768x320)"
    l = attendi(c, c.post(f"{base}/genera", json={"quantita": 1}).json()["id"])
    assert l["stato"] == "errore" and "non è per questo checkpoint" in l["errore"]
