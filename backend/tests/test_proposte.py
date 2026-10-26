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


def test_dataset_come_le_proposte(casa, finto_comfy, cartella_comfy):
    """Le scelte fatte creando il personaggio dal nulla (checkpoint, LoRA di stile, stile, negativo, campionamento)
    passano da sole al dataset, così il personaggio del dataset è lo stesso delle proposte."""
    stato = App(Archivio(casa / "impostazioni.json"))
    with TestClient(crea_app(stato, sorveglia=False)) as c:
        c.post("/api/comfy/usa", json={"url": finto_comfy.url, "cartella": str(cartella_comfy)})
        p = c.post("/api/progetti", json={"nome": "Western"}).json()["id"]
        c.post(f"/api/progetti/{p}/personaggi", json={"nome": "Jack", "genere": "1boy",
                                                      "descrizione": "short black hair, stubble, cowboy hat"})
        base = f"/api/progetti/{p}/personaggi/jack/proposte"
        conf = {"checkpoint": "ponyDiffusionV6XL.safetensors", "numero": 1, "stile": "western comics (style)",
                "extra": "ink lines", "lora_stile": "Comic_Style.safetensors", "forza_lora": 0.65,
                "negativo": "{negativo_qualita}, 3d, realistic", "passi": 24, "cfg": 7.0, "sampler": "dpmpp_2m"}
        # anteprima del prompt, senza generare
        a = c.post(f"{base}/anteprima", json=conf).json()
        assert a["famiglia"] == "pony" and a["positivo"].startswith("score_9, score_8_up, score_7_up, 1boy, solo")
        assert "western comics (style)" in a["positivo"] and a["negativo"] == "score_4, score_5, score_6, 3d, realistic"
        l = attendi(c, c.post(base, json=conf).json()["id"])
        assert l["stato"] == "completato", l["errore"]
        inviato = finto_comfy.ricevuti[-1]
        lora = next(n for n in inviato.values() if n["class_type"] == "LoraLoader")["inputs"]
        assert lora["lora_name"] == "Comic_Style.safetensors" and lora["strength_model"] == 0.65
        ks = next(n for n in inviato.values() if n["class_type"] == "KSampler")["inputs"]
        assert ks["steps"] == 24 and ks["sampler_name"] == "dpmpp_2m" and ks["model"] == ["10", 0]
        proposta = c.get(base).json()[0]
        assert proposta["ricetta"]["lora_stile"] == "Comic_Style.safetensors"
        assert proposta["ricetta"]["negativo"] == "{negativo_qualita}, 3d, realistic"

        # «Usa questa»: il riferimento ricorda come è nato e il dataset è già pronto con le stesse scelte
        pers = c.post(f"{base}/{proposta['file']}/scegli").json()
        assert pers["origine"]["checkpoint"] == "ponyDiffusionV6XL.safetensors"
        ds = c.get(f"/api/progetti/{p}/personaggi/jack/dataset").json()
        conf_ds = ds["config"]
        assert conf_ds["stile"] == "western comics (style), ink lines" and "{stile}" in conf_ds["prompt_positivo"]
        assert conf_ds["prompt_negativo"] == "{negativo_qualita}, 3d, realistic"
        assert ds["origine"]["coerente"] and ds["origine"]["checkpoint_workflow"] == "ponyDiffusionV6XL.safetensors"
        wf = c.get(f"/api/progetti/{p}/workflows/{conf_ds['workflow']}").json()
        nodi = wf["workflow"].values() if "workflow" in wf else []
        assert wf["parametri"]["lora_stile"] == "Comic_Style.safetensors" and wf["parametri"]["sampler"] == "dpmpp_2m"
        assert wf["parametri"]["ipadapter"] is None                 # IPAdapter non installato: txt2img
        assert not any(n["class_type"].startswith("IPAdapter") for n in nodi)
        assert any("IPAdapter non è installato" in e["msg"] for e in stato.bus.storico)
        # i prompt del dataset usano lo stesso stile e lo stesso negativo
        es = c.post(f"/api/progetti/{p}/personaggi/jack/dataset/esempi", json=conf_ds).json()[0]
        assert es["positivo"].startswith("score_9") and es["positivo"].endswith("western comics (style), ink lines")
        assert es["negativo"] == "score_4, score_5, score_6, 3d, realistic"

        # un altro workflow con un altro checkpoint: il dataset lo segnala
        altro = c.post(f"/api/progetti/{p}/workflows/integrato", json={
            "checkpoint": "waiIllustriousSDXL_v170.safetensors"}).json()
        c.put(f"/api/progetti/{p}/personaggi/jack/dataset/config", json=conf_ds | {"workflow": altro["id"]})
        ds = c.get(f"/api/progetti/{p}/personaggi/jack/dataset").json()
        assert not ds["origine"]["coerente"] and ds["origine"]["checkpoint_workflow"].startswith("waiIllustrious")
        # «Usa il workflow delle proposte»: torna quello di prima (non se ne crea un doppione), ora con IPAdapter
        finto_comfy.modelli |= {"ipadapter": ["ip-adapter-plus_sdxl_vit-h.safetensors"],
                                "clip_vision": ["CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"]}
        r = c.post(f"/api/progetti/{p}/personaggi/jack/dataset/come-proposte").json()
        assert r["origine"]["coerente"] and not r["avvisi"]
        assert r["workflow"]["parametri"]["ipadapter"] == "ip-adapter-plus_sdxl_vit-h.safetensors"
        assert r["workflow"]["ruoli"]["riferimento"] == "5"
        r2 = c.post(f"/api/progetti/{p}/personaggi/jack/dataset/come-proposte").json()
        assert r2["workflow"]["id"] == r["workflow"]["id"]

        # un riferimento caricato a mano non ha più origine
        dati = (stato.progetti.cartella_personaggio(p, "jack") / "riferimento.png").read_bytes()
        pers = c.put(f"/api/progetti/{p}/personaggi/jack/riferimento", files={"file": ("r.png", dati, "image/png")}).json()
        assert pers["origine"] is None
        assert c.get(f"/api/progetti/{p}/personaggi/jack/dataset").json()["origine"] is None
        assert c.post(f"/api/progetti/{p}/personaggi/jack/dataset/come-proposte").status_code == 400


def test_workflow_nei_log_e_grafo(casa, finto_comfy, cartella_comfy):
    """Il workflow che le proposte mandano a ComfyUI: riga nei log (una sola se cambiano solo prompt e seme),
    grafo con tipi e collegamenti, JSON da aprire in ComfyUI."""
    stato = App(Archivio(casa / "impostazioni.json"))
    with TestClient(crea_app(stato, sorveglia=False)) as c:
        c.post("/api/comfy/usa", json={"url": finto_comfy.url, "cartella": str(cartella_comfy)})
        p = c.post("/api/progetti", json={"nome": "G"}).json()["id"]
        c.post(f"/api/progetti/{p}/personaggi", json={"nome": "Ada", "descrizione": "red hair"})
        base = f"/api/progetti/{p}/personaggi/ada/proposte"
        l = attendi(c, c.post(base, json={"checkpoint": "ponyDiffusionV6XL.safetensors", "numero": 3,
                                          "lora_stile": "Comic_Style.safetensors"}).json()["id"])
        assert l["stato"] == "completato" and l["workflow"] == 3
        righe = [e for e in stato.bus.storico if e.get("grafo")]
        assert len(righe) == 1 and righe[0]["lavoro"] == l["id"]
        assert "CheckpointLoaderSimple ponyDiffusionV6XL → LoraLoader Comic_Style 0.8" in righe[0]["msg"]
        assert "KSampler (28 passi, CFG 6.0, euler_ancestral karras, denoise 1.0)" in righe[0]["msg"]
        r = c.get(f"/api/lavori/{l['id']}/workflow").json()
        g = r["grafo"]
        assert r["n"] == 3 and len(g["nodi"]) == 8 and g["nodi"][0]["classe"] == "CheckpointLoaderSimple"
        ck = g["nodi"][0]
        assert [u["tipo"] for u in ck["uscite"]] == ["MODEL", "CLIP", "VAE"]
        assert ck["widget"] == [{"nome": "ckpt_name", "valore": "ponyDiffusionV6XL.safetensors"}]
        ks = next(n for n in g["nodi"] if n["classe"] == "KSampler")
        assert {i["nome"]: i["tipo"] for i in ks["ingressi"]} == {
            "model": "MODEL", "positive": "CONDITIONING", "negative": "CONDITIONING", "latent_image": "LATENT"}
        assert {"da": "10", "uscita": 0, "a": "7", "ingresso": "model", "tipo": "MODEL"} in g["collegamenti"]
        assert len(g["collegamenti"]) == 11
        js = c.get(f"/api/lavori/{l['id']}/workflow.json")
        assert "attachment" in js.headers["content-disposition"]
        assert js.json()["7"]["class_type"] == "KSampler" and "_meta" not in js.json()["7"]
        # le varianti (img2img) cambiano la struttura: nuova riga nei log
        prop = c.get(base).json()[0]["file"]
        l2 = attendi(c, c.post(base, json={"checkpoint": "ponyDiffusionV6XL.safetensors", "numero": 1,
                                           "da": prop}).json()["id"])
        riga = [e for e in stato.bus.storico if e.get("grafo") and e["lavoro"] == l2["id"]][0]
        assert "LoadImage" in riga["msg"] and "denoise 0.55" in riga["msg"]
        assert c.get("/api/lavori/L999/workflow").status_code == 404
