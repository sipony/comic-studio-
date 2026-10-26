"""Impostazioni dei nodi cambiate dal grafo della console: cosa si può cambiare, controlli, dove finiscono."""
import pytest

from app import ritocchi
from test_dataset import ambiente, attendi, png  # noqa: F401 - fixture

# /object_info come quello di ComfyUI (solo i nodi che servono)
INFO = {
    "CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [["waiIllustriousSDXL_v170.safetensors",
                                                                     "ponyDiffusionV6XL.safetensors"]]}},
                               "output": ["MODEL", "CLIP", "VAE"], "output_name": ["MODEL", "CLIP", "VAE"]},
    "KSampler": {"input": {"required": {
        "model": ["MODEL"], "seed": ["INT", {"default": 0, "min": 0, "max": 2 ** 64 - 1}],
        "steps": ["INT", {"default": 20, "min": 1, "max": 10000}],
        "cfg": ["FLOAT", {"default": 8.0, "min": 0.0, "max": 100.0, "step": 0.1}],
        "sampler_name": [["euler", "euler_ancestral", "dpmpp_2m"]], "scheduler": [["normal", "karras"]],
        "positive": ["CONDITIONING"], "negative": ["CONDITIONING"], "latent_image": ["LATENT"],
        "denoise": ["FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}]}},
        "output": ["LATENT"], "output_name": ["LATENT"]},
    "CLIPTextEncode": {"input": {"required": {"text": ["STRING", {"multiline": True}], "clip": ["CLIP"]}},
                       "output": ["CONDITIONING"], "output_name": ["CONDITIONING"]},
    "EmptyLatentImage": {"input": {"required": {"width": ["INT", {"default": 512, "min": 16, "max": 16384}],
                                                "height": ["INT", {"default": 512, "min": 16, "max": 16384}],
                                                "batch_size": ["INT", {"default": 1, "min": 1, "max": 4096}]}},
                         "output": ["LATENT"], "output_name": ["LATENT"]},
}


def campo(r, nodo, ingresso):
    return r["impostazioni"]["campi"][nodo][ingresso]


def test_valida():
    s = {"tipo": "INT", "min": 1, "max": 100}
    assert ritocchi.valida("35", s) == (35, None) and ritocchi.valida(0, s)[1] == "il minimo è 1"
    assert ritocchi.valida(2.5, s)[1] == "serve un numero intero" and ritocchi.valida(True, s)[1] == "serve un numero"
    assert ritocchi.valida("6,5", {"tipo": "FLOAT", "min": 0, "max": 100}) == (6.5, None)
    assert ritocchi.valida("nan", {"tipo": "FLOAT"})[1] == "serve un numero"
    assert ritocchi.valida("x", {"tipo": "COMBO", "opzioni": ["a"]})[1] == "«x» non c'è tra le scelte possibili"
    assert ritocchi.valida(1, {"tipo": "STRING"})[1] == "serve un testo"
    sp = ritocchi.spec_ingresso("KSampler", "sampler_name", "euler", None, None)
    assert sp["tipo"] == "COMBO" and "dpmpp_2m" in sp["opzioni"]
    sp = ritocchi.spec_ingresso("LoraLoader", "lora_name", "a.safetensors", None, {"loras": ["b.safetensors"]})
    assert sp["opzioni"] == ["b.safetensors", "a.safetensors"]


def test_dataset(ambiente):  # noqa: F811
    c, p, stato, finto = ambiente
    finto.object_info = INFO
    base = f"/api/progetti/{p}"
    c.put(f"{base}/personaggi/agente/riferimento", files={"file": ("r.png", png(), "image/png")})
    wf = c.post(f"{base}/workflows/integrato", json={"checkpoint": "waiIllustriousSDXL_v170.safetensors"}).json()
    cfg = c.get(f"{base}/personaggi/agente/dataset").json()["config"] | {"workflow": wf["id"]}
    c.put(f"{base}/personaggi/agente/dataset/config", json=cfg)
    l = attendi(c, c.post(f"{base}/personaggi/agente/dataset/genera", json={"quantita": 1}).json()["id"])
    assert l["stato"] == "completato", l["errore"]
    r = c.get(f"/api/lavori/{l['id']}/workflow").json()
    assert r["impostazioni"]["sorgente"]["tipo"] == "dataset" and "Agente" in r["impostazioni"]["sorgente"]["descrizione"]
    # quello che Comic Studio scrive a ogni immagine non si cambia, e si dice dove cambiarlo
    assert "Prompt e varianti" in campo(r, "8", "text")["perche"] and not campo(r, "8", "text")["modificabile"]
    assert not campo(r, "11", "seed")["modificabile"] and not campo(r, "10", "width")["modificabile"]
    assert not campo(r, "13", "filename_prefix")["modificabile"]
    passi = campo(r, "11", "steps")
    assert passi["modificabile"] and passi["spec"] == {"tipo": "INT", "min": 1, "max": 10000, "step": None, "default": 20}
    assert campo(r, "1", "ckpt_name")["spec"]["opzioni"] == INFO["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
    url = f"/api/lavori/{l['id']}/workflow/impostazioni"
    # o tutte o nessuna
    e = c.post(url, json={"modifiche": {"11": {"steps": 0}}})
    assert e.status_code == 422 and e.json()["errori"][0]["errore"] == "il minimo è 1"
    e = c.post(url, json={"modifiche": {"11": {"steps": 35}, "8": {"text": "altro"}, "99": {"x": 1}}})
    assert e.status_code == 422 and len(e.json()["errori"]) == 2 and "Prompt e varianti" in e.json()["detail"]
    assert c.post(url, json={"modifiche": {"11": {"sampler_name": "nope"}}}).status_code == 422
    assert c.get(f"{base}/personaggi/agente/dataset").json()["config"]["modifiche"] == {}
    assert c.post(url, json={"modifiche": {}}).status_code == 400
    # salvate nelle impostazioni del dataset del personaggio, il workflow della libreria non cambia
    r = c.post(url, json={"modifiche": {"11": {"steps": 35, "sampler_name": "dpmpp_2m", "cfg": "7,5",
                                                "scheduler": "karras"},
                                         "1": {"ckpt_name": "ponyDiffusionV6XL.safetensors"}}}).json()
    mod = c.get(f"{base}/personaggi/agente/dataset").json()["config"]["modifiche"]
    assert mod == {"11": {"steps": 35, "sampler_name": "dpmpp_2m", "cfg": 7.5},
                   "1": {"ckpt_name": "ponyDiffusionV6XL.safetensors"}}       # scheduler era già karras: niente
    assert r["campi"]["11"]["steps"]["salvato"] == 35
    assert c.get(f"{base}/workflows/{wf['id']}").json()["workflow"]["11"]["inputs"]["steps"] == 30
    # la generazione dopo le usa
    l2 = attendi(c, c.post(f"{base}/personaggi/agente/dataset/genera", json={"quantita": 1}).json()["id"])
    inviato = finto.ricevuti[-1]
    assert inviato["11"]["inputs"]["steps"] == 35 and inviato["1"]["inputs"]["ckpt_name"] == "ponyDiffusionV6XL.safetensors"
    # None toglie la modifica (si torna al valore della libreria)
    c.post(f"/api/lavori/{l2['id']}/workflow/impostazioni", json={"modifiche": {"11": {"steps": None}}})
    assert "steps" not in c.get(f"{base}/personaggi/agente/dataset").json()["config"]["modifiche"]["11"]
    # il dataset passa a un altro workflow: il grafo del lavoro vecchio non si modifica più
    wf2 = c.post(f"{base}/workflows/integrato", json={"checkpoint": "ponyDiffusionV6XL.safetensors", "passi": 20}).json()
    cfg = c.get(f"{base}/personaggi/agente/dataset").json()["config"] | {"workflow": wf2["id"], "modifiche": {}}
    c.put(f"{base}/personaggi/agente/dataset/config", json=cfg)
    r = c.get(f"/api/lavori/{l2['id']}/workflow").json()
    assert r["impostazioni"]["sorgente"] is None and "altro workflow" in campo(r, "11", "steps")["perche"]


def test_proposte(ambiente):  # noqa: F811
    c, p, stato, finto = ambiente
    finto.object_info = INFO
    base = f"/api/progetti/{p}/personaggi/agente/proposte"
    l = attendi(c, c.post(base, json={"checkpoint": "waiIllustriousSDXL_v170.safetensors", "numero": 1,
                                      "stile": "western comics (style)"}).json()["id"])
    r = c.get(f"/api/lavori/{l['id']}/workflow").json()
    assert r["impostazioni"]["sorgente"]["tipo"] == "proposte"
    assert campo(r, "7", "steps")["modificabile"] and campo(r, "1", "ckpt_name")["modificabile"]
    assert "pannello" in campo(r, "2", "text")["perche"] and not campo(r, "7", "seed")["modificabile"]
    assert "varianti" in campo(r, "7", "denoise")["perche"] and not campo(r, "6", "width")["modificabile"]
    url = f"/api/lavori/{l['id']}/workflow/impostazioni"
    r = c.post(url, json={"modifiche": {"7": {"steps": 40, "cfg": 7, "sampler_name": "dpmpp_2m"},
                                         "1": {"ckpt_name": "ponyDiffusionV6XL.safetensors"}}}).json()
    pers = c.get(f"/api/progetti/{p}").json()["personaggi"][0]
    s = pers["scelte_proposte"]
    assert (s["checkpoint"], s["passi"], s["cfg"], s["sampler"], s["stile"]) == \
        ("ponyDiffusionV6XL.safetensors", 40, 7.0, "dpmpp_2m", "western comics (style)")
    assert r["campi"]["7"]["steps"]["salvato"] == 40
    # None torna al valore dell'ultima proposta
    c.post(url, json={"modifiche": {"7": {"steps": None}}})
    assert c.get(f"/api/progetti/{p}").json()["personaggi"][0]["scelte_proposte"]["passi"] == 28
    # un lavoro senza sorgente: tutto bloccato
    stato.gestore.lavori[l["id"]].contesto_workflow = None
    r = c.get(f"/api/lavori/{l['id']}/workflow").json()
    assert r["impostazioni"]["sorgente"] is None and not campo(r, "7", "steps")["modificabile"]
    assert c.post(url, json={"modifiche": {"7": {"steps": 30}}}).status_code == 422
