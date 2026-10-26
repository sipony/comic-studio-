"""Staccare nodi da un workflow: ricollegamenti automatici, catene, nodi staccati a cascata, problemi, API."""
import json

import pytest

from app.esclusione import escludi
from app.workflows import ErroreWorkflow, analizza, applica, integrato
from test_dataset import ambiente, attendi, png, wf_img2img  # noqa: F401 - fixture


def nodo(classe, titolo=None, **ing):
    return {"class_type": classe, "inputs": ing, "_meta": {"title": titolo or classe}}


def base(lora=2):
    """Checkpoint → LoRA (uno o due in fila) → prompt e KSampler → VAEDecode → SaveImage."""
    wf = {"1": nodo("CheckpointLoaderSimple", "Checkpoint", ckpt_name="ck.safetensors")}
    m, c = ["1", 0], ["1", 1]
    for k in range(lora):
        nid = str(20 + k)
        wf[nid] = nodo("LoraLoader", f"LoRA {k + 1}", model=m, clip=c, lora_name=f"l{k}.safetensors",
                       strength_model=1.0, strength_clip=1.0)
        m, c = [nid, 0], [nid, 1]
    wf |= {
        "4": nodo("CLIPTextEncode", "Positivo", clip=c, text="a"),
        "5": nodo("CLIPTextEncode", "Negativo", clip=c, text="b"),
        "6": nodo("EmptyLatentImage", width=832, height=1216, batch_size=1),
        "7": nodo("KSampler", "Sampler", model=m, positive=["4", 0], negative=["5", 0], latent_image=["6", 0],
                  seed=1, steps=20, cfg=6, sampler_name="euler", scheduler="karras", denoise=1.0),
        "8": nodo("VAEDecode", samples=["7", 0], vae=["1", 2]),
        "9": nodo("SaveImage", images=["8", 0], filename_prefix="x"),
    }
    return wf


def test_lora_staccato_si_ricollega_al_checkpoint():
    wf = base(lora=1)
    e = escludi(wf, ["20"])
    assert e.problemi == [] and e.esclusi == ["20"] and "20" not in e.wf
    assert e.wf["7"]["inputs"]["model"] == ["1", 0]
    assert e.wf["4"]["inputs"]["clip"] == ["1", 1] and e.wf["5"]["inputs"]["clip"] == ["1", 1]
    assert "#7 Sampler · model ← #1 Checkpoint" in [x["testo"] for x in e.dict()["collegamenti"]]
    assert wf["7"]["inputs"]["model"] == ["20", 0]           # l'originale non cambia


def test_catena_di_nodi_staccati():
    wf = base(lora=2)
    e = escludi(wf, ["20", "21"])
    assert e.problemi == [] and e.wf["7"]["inputs"]["model"] == ["1", 0] and e.wf["4"]["inputs"]["clip"] == ["1", 1]
    # solo il secondo: il primo resta e prende il posto
    e = escludi(wf, ["21"])
    assert e.wf["7"]["inputs"]["model"] == ["20", 0] and e.wf["5"]["inputs"]["clip"] == ["20", 1]


def test_controlnet_positivo_e_negativo_restano_al_loro_posto():
    wf = base(lora=0)
    wf["30"] = nodo("ControlNetLoader", control_net_name="openpose.safetensors")
    wf["31"] = nodo("LoadImage", "Posa", image="posa.png")
    wf["32"] = nodo("ControlNetApplyAdvanced", "ControlNet", positive=["4", 0], negative=["5", 0],
                    control_net=["30", 0], image=["31", 0], strength=0.8, start_percent=0, end_percent=1)
    wf["7"]["inputs"]["positive"] = ["32", 0]
    wf["7"]["inputs"]["negative"] = ["32", 1]
    e = escludi(wf, ["32"])
    assert e.wf["7"]["inputs"]["positive"] == ["4", 0] and e.wf["7"]["inputs"]["negative"] == ["5", 0]
    # staccare l'immagine della posa: il ControlNet non può funzionare e viene staccato a sua volta
    e = escludi(wf, ["31"])
    assert e.problemi == [] and [a["nodo"] for a in e.automatici] == ["32"]
    assert e.wf["7"]["inputs"]["positive"] == ["4", 0] and e.wf["7"]["inputs"]["negative"] == ["5", 0]


def test_riferimento_staccato_stacca_anche_ipadapter():
    wf, ruoli = integrato("ck.safetensors", "ip.safetensors", "cv.safetensors", lora_stile="stile.safetensors")
    wf["14"] = {"class_type": "PreviewImage", "inputs": {"images": ["5", 0]}, "_meta": {"title": "Anteprima"}}
    e = escludi(wf, ["5"], protetti=(ruoli.seme, ruoli.salva, ruoli.positivo))
    assert e.problemi == []
    assert {a["nodo"] for a in e.automatici} == {"6", "7", "14"}
    perche = {a["nodo"]: a["perche"] for a in e.automatici}
    assert "lascia passare" in perche["7"] and "usava solo" in perche["14"]
    # il KSampler prende il modello che entrava nell'IPAdapter (il LoRA di stile)
    assert e.wf["11"]["inputs"]["model"] == ["2", 0]


def test_quando_non_si_puo():
    wf = base(lora=1)
    # senza checkpoint non c'è niente da far passare: la catena arriva al prompt positivo, che non si tocca
    e = escludi(wf, ["1"], protetti=("7", "9", "4"))
    assert e.problemi and any("#4 Positivo" in p for p in e.problemi)
    # i nodi riconosciuti non si staccano
    e = escludi(wf, ["7"], protetti=("7", "9", "4"))
    assert any("#7 Sampler non si può staccare" in p for p in e.problemi)


def test_ingresso_facoltativo_tolto_con_le_definizioni_di_comfy():
    wf = base(lora=0)
    wf["40"] = nodo("MascheraFinta", image=["8", 0])
    wf["9"]["inputs"]["mask"] = ["40", 0]
    info = {"SaveImage": {"input": {"required": {"images": ["IMAGE"]}, "optional": {"mask": ["MASK"]}},
                          "output": []},
            "MascheraFinta": {"input": {"required": {"image": ["IMAGE"]}}, "output": ["MASK"]}}
    e = escludi(wf, ["40"], info)
    assert e.problemi == [] and "mask" not in e.wf["9"]["inputs"]
    assert any("mask tolto" in x["testo"] for x in e.dict()["collegamenti"])
    # nodi sconosciuti: con i tipi di ComfyUI si capisce cosa far passare
    wf2 = base(lora=0)
    wf2["50"] = nodo("NodoStrano", modello_in=["1", 0], forza=0.5)
    wf2["7"]["inputs"]["model"] = ["50", 0]
    info2 = {"NodoStrano": {"input": {"required": {"modello_in": ["MODEL"], "forza": ["FLOAT", {}]}},
                            "output": ["MODEL"]}}
    assert escludi(wf2, ["50"], protetti=("7", "9", "4")).problemi      # senza i tipi non si sa
    e = escludi(wf2, ["50"], info2, protetti=("7", "9", "4"))
    assert e.problemi == [] and e.wf["7"]["inputs"]["model"] == ["1", 0]


def test_img2img_riferimento_staccato_con_le_pose_dalle_varianti():
    wf = wf_img2img()
    r = analizza(wf).ruoli
    w = applica(wf, r, dimensioni=(832, 1216), composizione_libera=True, disattivati=["20"])
    assert "20" not in w and "22" not in w and "21" not in w and w["7"]["inputs"]["latent_image"] == ["cs_latente", 0]
    # tenendo la composizione del riferimento, senza riferimento il KSampler non ha da dove partire
    with pytest.raises(ErroreWorkflow, match="non si può|bisogno"):
        applica(wf, r, dimensioni=(832, 1216), composizione_libera=False, disattivati=["20"])


def test_api_anteprima_e_generazione_con_nodi_staccati(ambiente):  # noqa: F811
    c, p, stato, finto = ambiente
    b = f"/api/progetti/{p}"
    r = c.post(f"{b}/workflows", files={"file": ("img2img.json", json.dumps(wf_img2img()).encode(), "application/json")})
    cfg = c.get(f"{b}/personaggi/agente/dataset").json()["config"]
    cfg["workflow"] = r.json()["id"]
    cfg["disattivati"] = ["2"]                                      # il LoRA
    e = c.post(f"{b}/personaggi/agente/dataset/esclusione", json=cfg).json()
    assert e["ok"] and e["esclusi"] == ["2"] and "tipi_da_comfy" in e
    assert any(x["testo"] == "#7 KSampler · model ← #1 CheckpointLoaderSimple" for x in e["collegamenti"])
    # anche il riferimento: con le pose dalle varianti non serve, e non si chiede di caricarlo
    cfg["disattivati"] = ["2", "20"]
    e = c.post(f"{b}/personaggi/agente/dataset/esclusione", json=cfg).json()
    assert e["ok"] and set(e["esclusi"]) >= {"2", "20", "21", "22"}
    c.put(f"{b}/personaggi/agente/dataset/config", json=cfg)
    l = attendi(c, c.post(f"{b}/personaggi/agente/dataset/genera", json={"quantita": 1}).json()["id"])
    assert l["stato"] == "completato", l["errore"]
    inviato = finto.ricevuti[-1]
    assert not {"2", "20", "21", "22"} & set(inviato) and inviato["7"]["inputs"]["model"] == ["1", 0]
    assert any("Nodi staccati" in r["msg"] for r in c.get("/api/log").json())
    # se non si può, la generazione non parte e spiega perché
    cfg["disattivati"] = ["1"]
    c.put(f"{b}/personaggi/agente/dataset/config", json=cfg)
    r = c.post(f"{b}/personaggi/agente/dataset/genera", json={"quantita": 1})
    assert r.status_code == 400 and "staccati" in r.json()["detail"]
