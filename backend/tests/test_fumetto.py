import io
import time
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import fumetto as fm
from app.addestramento import ArchivioAddestramento
from app.main import crea_app
from app.projects import Personaggio
from app.settings import Archivio
from app.state import App


def pers(i, genere="1girl"):
    return Personaggio(id=f"p{i}", nome=f"Pers {i}", trigger=f"trg{i}x", genere=genere, descrizione=f"tratto {i}")


def classi(wf):
    return [n["class_type"] for n in wf.values()]


def test_workflow_uno_e_zero_personaggi():
    imp = fm.Impostazioni(checkpoint="ck.safetensors", lora_stile="stile.safetensors")
    v = fm.Vignetta(formato="alta", personaggi=["p1"], azione="running in the rain")
    wf, salva, prompt = fm.Costruttore(imp, ("masterpiece", "worst quality")).costruisci(v, [pers(1)], {"p1": "comic_studio/trg1x.safetensors"}, 7)
    assert classi(wf).count("LoraLoader") == 2 and wf[salva]["class_type"] == "SaveImage"
    assert prompt.startswith("masterpiece, western comics") and "trg1x, 1girl, solo, running in the rain" in prompt
    assert "tratto 1" not in prompt                                     # con il LoRA basta la trigger
    lat = next(n for n in wf.values() if n["class_type"] == "EmptyLatentImage")["inputs"]
    assert (lat["width"], lat["height"]) == (832, 1216)
    _, _, p2 = fm.Costruttore(imp, ("q", "n")).costruisci(v, [pers(1)], {}, 7)
    assert "tratto 1" in p2                                             # senza LoRA servono i tratti
    wf, _, p3 = fm.Costruttore(imp, ("q", "n")).costruisci(fm.Vignetta(azione="city"), [], {}, 1)
    assert "no humans" in p3 and classi(wf).count("LoraLoader") == 1
    with pytest.raises(fm.ErroreProgetto):
        fm.Costruttore(fm.Impostazioni(), ("", "")).costruisci(v, [], {}, 1)


def test_workflow_tre_personaggi():
    imp = fm.Impostazioni(checkpoint="ck.safetensors")
    v = fm.Vignetta(formato="larga", personaggi=["p1", "p2", "p3"], azione="walking")
    lora = {"p1": "a.safetensors", "p2": "b.safetensors", "p3": None}
    wf, salva, prompt = fm.Costruttore(imp, ("q", "n")).costruisci(v, [pers(1), pers(2, "1boy"), pers(3)], lora, 5)
    c = classi(wf)
    assert c.count("ConditioningSetMask") == 3 and c.count("InpaintModelConditioning") == 3
    assert c.count("KSampler") == 4 and c.count("ImageCompositeMasked") == 3
    assert "2girls, 1boy" in prompt and "trg2x in the center" in prompt
    zone = [n["inputs"]["x"] for n in wf.values() if n["class_type"] == "MaskComposite"]
    assert zone == sorted(zone) and zone[0] == 0
    for k, n in wf.items():
        for val in n["inputs"].values():
            if isinstance(val, list):
                assert val[0] in wf


def test_importa_storia():
    p = [pers(1), Personaggio(id="comm", nome="Commissario", trigger="cmsrold", genere="1boy")]
    pagine = fm.importa_storia("""
# commento
larga | nessuno | police station at night | narratore: Distretto 9
larga | pers 1 + commissario | office | trg1x: Ciao | Commissario: Salve
---
alta | cmsrold | reading
""", p)
    assert len(pagine) == 2 and len(pagine[0].vignette) == 2
    v = pagine[0].vignette[1]
    assert v.personaggi == ["p1", "comm"] and [d.chi for d in v.dialoghi] == ["p1", "comm"]
    assert pagine[0].vignette[0].dialoghi[0].chi == "narratore"
    with pytest.raises(fm.ErroreProgetto, match="sconosciuti"):
        fm.importa_storia("larga | chi? | x", p)


def test_impaginazione_e_balloon():
    vs = [fm.Vignetta(formato="larga", dialoghi=[fm.Dialogo(testo="Distretto 9, ore 23:40.")]),
          fm.Vignetta(formato="alta", personaggi=["p1", "p2"],
                      dialoghi=[fm.Dialogo(chi="p1", testo="Ciao! " * 20), fm.Dialogo(chi="p2", testo="Ehi.")]),
          fm.Vignetta(formato="alta", dialoghi=[fm.Dialogo(chi="p1", testo="Giù", posizione="basso-dx")]),
          fm.Vignetta(formato="quadrata")]
    p = fm.Pagina(vignette=vs)
    assert [len(r) for r in fm.righe_pagina(p)] == [1, 2, 1]
    img = fm.componi_pagina(p, lambda v: fm.disegna_balloon(fm.segnaposto(v, {}), v, None), fm.Impostazioni())
    assert img.width == 1736 and img.height > 2000
    con = fm.disegna_balloon(Image.new("RGB", (832, 1216), "gray"), vs[2], None)
    assert con.getpixel((832 - 40, 1216 - 120)) != (128, 128, 128)       # balloon in basso a destra
    assert fm.pdf([img, img])[:4] == b"%PDF"


def png(c, w=64, h=96):
    b = io.BytesIO()
    Image.new("RGB", (w, h), c).save(b, "PNG")
    return b.getvalue()


def test_flusso_fumetto(casa, finto_comfy, cartella_comfy):
    stato = App(Archivio(casa / "impostazioni.json"))
    c = TestClient(crea_app(stato, sorveglia=False))
    with c:
        c.post("/api/comfy/usa", json={"url": finto_comfy.url, "cartella": str(cartella_comfy)})
        p = c.post("/api/progetti", json={"nome": "Storia"}).json()["id"]
        c.post(f"/api/progetti/{p}/personaggi", json={"nome": "Agente", "trigger": "vglcop"})
        c.post(f"/api/progetti/{p}/personaggi", json={"nome": "Commissario", "trigger": "cmsrold", "genere": "1boy"})
        a = ArchivioAddestramento(stato.progetti)
        s = a.stato(p, "agente")
        s.lora_finale = "comic_studio/vglcop.safetensors"
        a.salva_stato(p, "agente", s)
        base = f"/api/progetti/{p}/fumetto"
        r = c.get(base).json()
        assert r["lora"] == {"agente": "comic_studio/vglcop.safetensors", "commissario": None}
        r = c.post(f"{base}/importa", json={"testo": "larga | agente + commissario | office | agente: Ciao\nalta | nessuno | street"}).json()
        f = r["fumetto"]
        assert len(f["pagine"]) == 1 and len(f["pagine"][0]["vignette"]) == 2
        assert c.post(f"{base}/genera", json={}).status_code == 400            # manca il checkpoint
        f["impostazioni"]["checkpoint"] = "ck0.safetensors"
        f["pagine"][0]["vignette"][1]["dialoghi"] = [{"chi": "fantasma", "testo": "Boo"}]
        assert c.put(base, json=f).status_code == 200
        assert c.get(base).json()["fumetto"]["pagine"][0]["vignette"][1]["dialoghi"][0]["chi"] == "narratore"
        lid = c.post(f"{base}/genera", json={}).json()["id"]
        for _ in range(300):
            l = next(x for x in c.get("/api/lavori").json() if x["id"] == lid)
            if l["stato"] not in ("in_coda", "in_corso"):
                break
            time.sleep(0.02)
        assert l["stato"] == "completato", l["errore"]
        log = [x["msg"] for x in c.get("/api/log").json()]
        assert any("Commissario non ha ancora un LoRA" in m for m in log)
        imm = c.get(base).json()["immagini"]
        v1, v2 = (v["id"] for v in f["pagine"][0]["vignette"])
        assert len(imm[v1]["versioni"]) == 1 and imm[v1]["scelta"] == 0
        inviato = finto_comfy.ricevuti[-2]
        assert sum(n["class_type"] == "InpaintModelConditioning" for n in inviato.values()) == 2
        # rigenera con lo stesso seme: nuova versione, stesso seme
        lid = c.post(f"{base}/genera", json={"vignette": [v1], "stesso_seme": True}).json()["id"]
        for _ in range(300):
            if next(x for x in c.get("/api/lavori").json() if x["id"] == lid)["stato"] == "completato":
                break
            time.sleep(0.02)
        imm = c.get(base).json()["immagini"][v1]
        assert len(imm["versioni"]) == 2 and imm["versioni"][0]["seme"] == imm["versioni"][1]["seme"]
        assert c.put(f"{base}/vignette/{v1}/scelta", json={"indice": 0}).json()["scelta"] == 0
        assert c.get(f"{base}/immagini/{imm['versioni'][0]['file']}").status_code == 200
        r = c.get(f"{base}/pagine/0/anteprima?larghezza=600")
        assert r.headers["content-type"] == "image/jpeg" and Image.open(io.BytesIO(r.content)).width == 600
        assert c.get(f"{base}/pagine/5/anteprima").status_code == 404
        r = c.get(f"{base}/esporta?formato=pdf")
        assert r.content[:4] == b"%PDF"
        z = zipfile.ZipFile(io.BytesIO(c.get(f"{base}/esporta?formato=zip").content))
        assert z.namelist() == ["storia_pagina_01.png"]


def test_fumetto_nuovo_con_lo_stile_dei_personaggi(tmp_path):
    """Un fumetto nuovo parte dal checkpoint, dalla LoRA di stile e dai tag di stile delle proposte dei personaggi."""
    from app.projects import Archivio as ArchivioProgetti, ModificaPersonaggio, NuovoPersonaggio
    pr = ArchivioProgetti(tmp_path)
    pid = pr.crea("Fumetto").id
    c = pr.aggiungi_personaggio(pid, NuovoPersonaggio(nome="Ada"))
    assert fm.ArchivioFumetto(pr).leggi(pid).impostazioni.lora_stile is None
    pr.modifica_personaggio(pid, c.id, ModificaPersonaggio(origine={
        "checkpoint": "wai.safetensors", "lora_stile": "KonicsXL_Style.safetensors", "forza_lora": 0.8,
        "stile": "western comics"}))
    imp = fm.ArchivioFumetto(pr).leggi(pid).impostazioni
    assert (imp.checkpoint, imp.lora_stile, imp.forza_stile) == ("wai.safetensors", "KonicsXL_Style.safetensors", 0.8)
    assert imp.positivo == "{qualita}, western comics"
