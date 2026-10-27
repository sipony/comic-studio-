"""«Ho già il prompt»: proposte con il prompt dell'utente così com'è, e dataset che lo riusa con le varianti."""
from fastapi.testclient import TestClient

from app import rotte_dataset
from app.main import crea_app
from app.proposte import dividi_tag, e_variabile, modello_da_prompt_proprio
from app.settings import Archivio
from app.state import App
from test_dataset import attendi

PROMPT = ("masterpiece, best quality, amazing quality, 1girl, solo, (red hair:1.2), nun, black habit, looking at viewer, "
          "(full body:1.1), standing, smile, simple background, white background, (pelvic curtain, cross necklace:1.1), "
          "heart tattoo, western comics")
NEGATIVO = "worst quality, (bad hands:1.3), text, watermark"


def test_divisione_del_prompt():
    assert dividi_tag("a, (b, c:1.2), [d]") == ["a", "(b, c:1.2)", "[d]"]
    assert e_variabile("(full body:1.1)") and e_variabile("white background") and e_variabile("smiling")
    assert not e_variabile("(red hair:1.2)") and not e_variabile("looking at viewer") and not e_variabile("nun")
    assert modello_da_prompt_proprio(PROMPT) == (
        "masterpiece, best quality, amazing quality, 1girl, solo, (red hair:1.2), nun, black habit, looking at viewer, "
        "{aspetto}, {inquadratura}, {posa}, {angolazione}, {espressione}, {sfondo}, (pelvic curtain, cross necklace:1.1), "
        "heart tattoo, western comics")


def test_proposte_e_dataset_dal_prompt_proprio(casa, finto_comfy, cartella_comfy, monkeypatch):
    class TaggerFinto:
        def tagga(self, immagini, *a, **k):
            return {immagini[0].name: {"red hair": 0.95, "nun": 0.9, "black thighhighs": 0.7, "smile": 0.6,
                                       "white background": 0.9}}
    monkeypatch.setattr(rotte_dataset, "carica_tagger", lambda *a, **k: TaggerFinto())
    stato = App(Archivio(casa / "impostazioni.json"))
    with TestClient(crea_app(stato, sorveglia=False)) as c:
        c.post("/api/comfy/usa", json={"url": finto_comfy.url, "cartella": str(cartella_comfy)})
        p = c.post("/api/progetti", json={"nome": "Convento"}).json()["id"]
        c.post(f"/api/progetti/{p}/personaggi", json={"nome": "Suora", "genere": "1girl"})     # niente descrizione
        base = f"/api/progetti/{p}/personaggi/suora"
        conf = {"checkpoint": "waiIllustriousSDXL_v170.safetensors", "numero": 1, "inquadratura": "figura_intera",
                "stile": "", "extra": "", "positivo": PROMPT, "negativo": NEGATIVO,
                "lora_stile": "Comic_Style.safetensors"}
        a = c.post(f"{base}/proposte/anteprima", json=conf).json()
        assert a["positivo"] == PROMPT and a["negativo"] == NEGATIVO and a["proprio"]
        assert "LoRA" in c.post(f"{base}/proposte/anteprima",
                                json=conf | {"positivo": PROMPT + ", <lora:x:0.8>"}).json()["nota"]
        r = c.post(f"{base}/proposte", json=conf | {"positivo": "<lora:x:1>, 1girl"})
        assert r.status_code == 400 and "A1111" in r.json()["detail"]

        l = attendi(c, c.post(f"{base}/proposte", json=conf).json()["id"])
        assert l["stato"] == "completato", l["errore"]
        testi = [n["inputs"]["text"] for n in finto_comfy.ricevuti[-1].values() if n["class_type"] == "CLIPTextEncode"]
        assert testi == [PROMPT, NEGATIVO]                                # parola per parola
        prop = c.get(f"{base}/proposte").json()[0]
        assert prop["ricetta"]["positivo"] == PROMPT

        c.post(f"{base}/proposte/{prop['file']}/scegli")
        ds = c.get(f"{base}/dataset").json()
        assert ds["config"]["prompt_positivo"] == modello_da_prompt_proprio(PROMPT)
        assert ds["config"]["prompt_negativo"] == NEGATIVO and ds["config"]["stile"] == ""
        assert ds["origine"]["coerente"], ds["origine"]

        l = attendi(c, c.post(f"{base}/dataset/somiglianza").json()["id"])
        assert l["stato"] == "completato", l["errore"]
        cfg = c.get(f"{base}/dataset").json()["config"]
        assert cfg["aspetto"] == "black thighhighs"                       # «red hair», «nun» già nel prompt
        assert cfg["prompt_positivo"] == modello_da_prompt_proprio(PROMPT)
        assert c.get(f"{base}/dataset").json()["origine"]["coerente"]

        l = attendi(c, c.post(f"{base}/dataset/genera", json={"quantita": 2}).json()["id"])
        assert l["stato"] == "completato", l["errore"]
        img = c.get(f"{base}/dataset/immagini").json()[-1]
        assert img["prompt"].startswith("masterpiece, best quality, amazing quality, 1girl, solo, (red hair:1.2), nun, "
                                        "black habit, looking at viewer, black thighhighs, ")
        assert img["prompt"].endswith("simple background, white background, (pelvic curtain, cross necklace:1.1), "
                                      "heart tattoo, western comics")
        neg = [n["inputs"]["text"] for n in finto_comfy.ricevuti[-1].values() if n["class_type"] == "CLIPTextEncode"][1]
        assert neg == NEGATIVO
