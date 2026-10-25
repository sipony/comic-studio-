import json
from pathlib import Path

import pytest

from app.workflows import ErroreWorkflow, Ruoli, analizza, applica, controlla_ruoli, formato, integrato, normalizza, per_invio

DATI = Path(__file__).parent / "dati"

# definizioni dei nodi come le restituisce /object_info (ridotte all'essenziale)
OBJECT_INFO = {
    "CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [["a.safetensors", "b.safetensors"]]}}},
    "CLIPTextEncode": {"input": {"required": {"text": ["STRING", {"multiline": True}], "clip": ["CLIP"]}}},
    "EmptyLatentImage": {"input": {"required": {"width": ["INT", {}], "height": ["INT", {}], "batch_size": ["INT", {}]}}},
    "KSampler": {"input": {"required": {
        "model": ["MODEL"], "seed": ["INT", {"control_after_generate": True}], "steps": ["INT", {}],
        "cfg": ["FLOAT", {}], "sampler_name": [["euler", "euler_ancestral"]], "scheduler": [["normal", "karras"]],
        "positive": ["CONDITIONING"], "negative": ["CONDITIONING"], "latent_image": ["LATENT"],
        "denoise": ["FLOAT", {}]}}},
    "VAEDecode": {"input": {"required": {"samples": ["LATENT"], "vae": ["VAE"]}}},
    "SaveImage": {"input": {"required": {"images": ["IMAGE"], "filename_prefix": ["STRING", {}]}}},
    "LoadImage": {"input": {"required": {"image": [["x.png"], {"image_upload": True}]}}},
    "LoraLoader": {"input": {"required": {"model": ["MODEL"], "clip": ["CLIP"], "lora_name": [["l.safetensors"]],
                                          "strength_model": ["FLOAT", {}], "strength_clip": ["FLOAT", {}]}}},
    "ImageScale": {"input": {"required": {"image": ["IMAGE"], "upscale_method": [["lanczos"]], "width": ["INT", {}],
                                          "height": ["INT", {}], "crop": [["disabled"]]}}},
}


def nodo(id_, tipo, valori=None, ingressi=(), uscite=(), modo=0, titolo=None):
    n = {"id": id_, "type": tipo, "mode": modo, "widgets_values": valori or [],
         "inputs": [{"name": nome, "type": t, "link": link} for nome, t, link in ingressi],
         "outputs": [{"name": t, "type": t, "links": []} for t in uscite]}
    if titolo:
        n["title"] = titolo
    return n


def workflow_ui(link_oggetti=False):
    nodi = [
        nodo(4, "CheckpointLoaderSimple", ["b.safetensors"], uscite=["MODEL", "CLIP", "VAE"]),
        nodo(10, "LoraLoader", ["l.safetensors", 0.8, 0.8], [("model", "MODEL", 1), ("clip", "CLIP", 2)],
             ["MODEL", "CLIP"], modo=4),                       # in bypass
        nodo(20, "Reroute", [], [("", "*", 3)], ["CLIP"]),
        nodo(6, "CLIPTextEncode", ["a girl, smiling"], [("clip", "CLIP", 4)], ["CONDITIONING"], titolo="Positivo"),
        nodo(7, "CLIPTextEncode", ["lowres"], [("clip", "CLIP", 5)], ["CONDITIONING"]),
        nodo(5, "EmptyLatentImage", [832, 1216, 4], uscite=["LATENT"]),
        nodo(30, "PrimitiveNode", [33], uscite=["INT"]),
        nodo(3, "KSampler", [156680208700286, "randomize", 25, 6.5, "euler_ancestral", "karras", 1.0],
             [("model", "MODEL", 6), ("positive", "CONDITIONING", 7), ("negative", "CONDITIONING", 8),
              ("latent_image", "LATENT", 9), ("steps", "INT", 13)], ["LATENT"]),
        nodo(8, "VAEDecode", [], [("samples", "LATENT", 10), ("vae", "VAE", 11)], ["IMAGE"]),
        nodo(9, "SaveImage", ["ComfyUI"], [("images", "IMAGE", 12)]),
        nodo(40, "ImageScale", ["lanczos", 512, 512, "disabled"], [("image", "IMAGE", 14)], ["IMAGE"], modo=2),
        nodo(50, "Note", ["appunti"]),
    ]
    nodi[7]["inputs"][4]["widget"] = {"name": "steps"}
    link = [[1, 4, 0, 10, 0, "MODEL"], [2, 4, 1, 10, 1, "CLIP"], [3, 10, 1, 20, 0, "CLIP"],
            [4, 20, 0, 6, 0, "CLIP"], [5, 4, 1, 7, 0, "CLIP"], [6, 10, 0, 3, 0, "MODEL"],
            [7, 6, 0, 3, 1, "CONDITIONING"], [8, 7, 0, 3, 2, "CONDITIONING"], [9, 5, 0, 3, 3, "LATENT"],
            [10, 3, 0, 8, 0, "LATENT"], [11, 4, 2, 8, 1, "VAE"], [12, 8, 0, 9, 0, "IMAGE"],
            [13, 30, 0, 3, 4, "INT"], [14, 8, 0, 40, 0, "IMAGE"]]
    if link_oggetti:
        link = [{"id": l[0], "origin_id": l[1], "origin_slot": l[2], "target_id": l[3], "target_slot": l[4],
                 "type": l[5]} for l in link]
    return {"nodes": nodi, "links": link, "version": 0.4}


@pytest.mark.parametrize("link_oggetti", [False, True])
def test_conversione_da_interfaccia(link_oggetti):
    ui = workflow_ui(link_oggetti)
    assert formato(ui) == "ui"
    wf, avvisi = normalizza(ui, OBJECT_INFO)
    assert set(wf) == {"4", "6", "7", "5", "3", "8", "9"}            # niente bypass, reroute, note, disattivati
    ks = wf["3"]["inputs"]
    assert ks["seed"] == 156680208700286 and ks["cfg"] == 6.5 and ks["sampler_name"] == "euler_ancestral"
    assert ks["steps"] == 33                                       # dal nodo Primitive
    assert ks["model"] == ["4", 0]                                 # il LoRA in bypass viene saltato
    assert wf["6"]["inputs"] == {"text": "a girl, smiling", "clip": ["4", 1]}   # attraverso Reroute e bypass
    assert wf["5"]["inputs"] == {"width": 832, "height": 1216, "batch_size": 4}
    assert wf["6"]["_meta"]["title"] == "Positivo"
    assert avvisi == []


def test_conversione_errori():
    with pytest.raises(ErroreWorkflow, match="serve\\s+ComfyUI"):
        normalizza(workflow_ui(), None)
    ui = workflow_ui()
    ui["nodes"].append(nodo(99, "NodoSconosciuto"))
    with pytest.raises(ErroreWorkflow, match="NodoSconosciuto"):
        normalizza(ui, OBJECT_INFO)
    with pytest.raises(ErroreWorkflow, match="subgraph"):
        normalizza({"nodes": [], "definitions": {"subgraphs": [{}]}}, OBJECT_INFO)
    with pytest.raises(ErroreWorkflow, match="non sembra"):
        normalizza({"ciao": 1}, OBJECT_INFO)


def test_formato_api_e_avvolto():
    wf, _ = integrato("a.safetensors", "ip.safetensors", "cv.safetensors")
    assert normalizza(wf, None)[0] == wf
    assert normalizza({"prompt": wf, "extra": {}}, None)[0] == wf


def test_analisi_workflow_integrato():
    wf, ruoli = integrato("waiIllustriousSDXL.safetensors", "ip.safetensors", "cv.safetensors", lora_stile="stile.safetensors")
    a = analizza(wf)
    assert a.ruoli == ruoli
    assert a.checkpoint == "waiIllustriousSDXL.safetensors" and a.lora == ["stile.safetensors"]
    assert controlla_ruoli(wf, ruoli) == []


def test_analisi_workflow_reale_a_quattro_vignette():
    wf = json.loads((DATI / "workflow_api_4_vignette.json").read_text())
    a = analizza(wf)
    assert a.ruoli.riferimento == "2"                  # il LoadImage che va all'IPAdapter
    assert a.ruoli.negativo == "6"                     # negativo comune
    assert a.ruoli.positivo in {"10", "20", "30", "40"}
    assert a.ruoli.latente == "7" and a.ruoli.seme in {"11", "21", "31", "41"}
    assert a.ruoli.salva in {"13", "23", "33", "43", "55"}
    assert len(a.candidati["positivo"]) == 5


def test_applica_non_tocca_i_collegamenti():
    wf, r = integrato("a.safetensors", "ip.safetensors", "cv.safetensors")
    w = applica(wf, r, riferimento="sub/rif.png", positivo="1girl, smile", negativo="lowres", seme=42,
                dimensioni=(1024, 1024), prefisso="cs/x", modifiche={"11": {"steps": 20, "model": "rotto"}, "99": {"a": 1}})
    assert w["5"]["inputs"]["image"] == "sub/rif.png"
    assert w["8"]["inputs"]["text"] == "1girl, smile" and w["9"]["inputs"]["text"] == "lowres"
    assert w["11"]["inputs"]["seed"] == 42 and w["11"]["inputs"]["steps"] == 20
    assert w["11"]["inputs"]["model"] == ["7", 0]                  # i collegamenti restano
    assert w["10"]["inputs"] == {"width": 1024, "height": 1024, "batch_size": 1}
    assert w["13"]["inputs"]["filename_prefix"] == "cs/x"
    assert wf["8"]["inputs"]["text"] == ""                         # l'originale non cambia
    assert "_meta" not in per_invio(w)["5"]


def test_controlla_ruoli_sbagliati():
    wf, _ = integrato("a.safetensors", "ip.safetensors", "cv.safetensors")
    errori = controlla_ruoli(wf, Ruoli(positivo="11", seme="8", latente="99"))
    assert len(errori) == 3
