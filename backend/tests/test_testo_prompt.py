"""Dal testo in linguaggio naturale al prompt: composizione, blocco fisso, aderenza, IA locale (finta)."""
import copy
import io
import tarfile
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from app import fumetto as fm
from app import llm
from app import testo_prompt as tp
from app.main import crea_app
from app.projects import Personaggio
from app.settings import Archivio
from app.state import App
from finto_ollama import SCENA, FintoOllama


@pytest.fixture
def finto_ollama():
    f = FintoOllama().avvia()
    yield f
    f.ferma()


MARA = Personaggio(id="mara", nome="Mara", trigger="mrhunt", descrizione="long wavy auburn hair, green eyes")


# ---------------------------------------------------------------- composizione

def test_scena_a_tag_per_illustrious():
    s = tp.componi_scena(SCENA, "illustrious", {"mara"})
    assert s.personaggi == ["mara"] and s.altri_soggetti == 1
    assert s.per_personaggio["mara"] == "holding axe, running, leaning forward, screaming, torn clothes, blood on clothes"
    assert s.globale.startswith("wide shot, from below, fighting, (zombie:1.15), rotting flesh, reaching out")
    assert "(blood splatter:1.15)" in s.globale and "(corridor:1.15)" in s.globale
    assert "(axe:1.15)" in s.globale            # elemento chiave che non era in nessuna lista
    assert "A woman" not in s.globale and s.negativo == "sunlight"


def test_scena_a_frasi_per_flux_e_rafforzati():
    s = tp.componi_scena(SCENA, "flux", {"mara"}, rafforza=["broken window"])
    assert s.globale.startswith("A woman with an axe fights a zombie")
    assert "(broken window:1.30)" in s.globale
    misto = tp.componi_scena(SCENA, "sdxl", {"mara"})
    assert misto.globale.endswith("dark hospital corridor.")


def test_costruttore_usa_azioni_per_personaggio():
    imp = fm.Impostazioni(checkpoint="ck.safetensors")
    commissario = Personaggio(id="cms", nome="Commissario", trigger="cmsold", genere="1boy")
    scena = tp.componi_scena(SCENA, "illustrious", {"mara", "cms"})
    v = fm.Vignetta(personaggi=["mara"], azione="night")
    wf, _, prompt = fm.Costruttore(imp, ("best quality", "worst quality")).costruisci(v, [MARA], {}, 1, scena)
    assert "screaming" in prompt and "zombie" in prompt and "night" in prompt and ", solo" not in prompt
    negativi = [n["inputs"]["text"] for n in wf.values() if n["class_type"] == "CLIPTextEncode"]
    assert any(t.endswith("sunlight") for t in negativi)
    v2 = fm.Vignetta(personaggi=["mara", "cms"])
    wf, _, _ = fm.Costruttore(imp, ("", "")).costruisci(v2, [MARA, commissario], {}, 1, scena)
    testi = [n["inputs"]["text"] for n in wf.values() if n["class_type"] == "CLIPTextEncode"]
    assert any(t.startswith("mrhunt, 1girl, long wavy auburn hair, green eyes, holding axe") for t in testi)


# ---------------------------------------------------------------- blocco fisso

def test_blocco_minori_e_contenuto_sessuale():
    with pytest.raises(tp.ContenutoVietato):
        tp.verifica_contenuto(["Una ragazzina di 12 anni, nuda"])
    with pytest.raises(tp.ContenutoVietato):
        tp.verifica_contenuto(["school uniform"], sessuale=True, minori=True)
    analisi = copy.deepcopy(SCENA)
    analisi["sessuale"] = True
    analisi["soggetti"][1]["adulto"] = False
    with pytest.raises(tp.ContenutoVietato):
        tp.verifica_scena(analisi, "testo", [MARA])
    giovane = MARA.model_copy(update={"adulto": False})
    analisi["soggetti"][1]["adulto"] = True
    with pytest.raises(tp.ContenutoVietato):
        tp.verifica_scena(analisi, "testo", [giovane])
    # horror e gore restano permessi, anche con un bambino nella scena
    tp.verifica_contenuto(["Un bambino urla mentre lo zombie sbrana il dottore, sangue ovunque"])
    tp.verifica_scena(SCENA, "massacro nell'ospedale", [giovane])


def test_aderenza_e_tratti():
    r = tp.aderenza({"zombie": 0.9, "axe": 0.1, "corridor": 0.5}, ["zombie", "axe", "corridor", "ospedale"],
                    {"zombie", "axe", "corridor"})
    assert r == {"trovati": ["zombie", "corridor"], "mancanti": ["axe"], "non_verificabili": ["ospedale"],
                 "punteggio": 0.67}
    from finto_ollama import PERSONAGGIO
    t = tp.tratti_personaggio(PERSONAGGIO, "pony")
    assert t["descrizione"].startswith("long wavy auburn hair, green eyes") and t["genere"] == "1girl"


def test_storia_spezzata_e_ripulita():
    testo = "\n\n".join(f"Paragrafo {i}. " + "parola " * 300 for i in range(10))
    pezzi = tp.spezza_storia(testo, 6000)
    assert len(pezzi) > 1 and all(len(p) <= 6000 for p in pezzi) and "".join(pezzi).count("Paragrafo") == 10
    from finto_ollama import STORIA
    pagine = tp.pagine_da_analisi(STORIA, [MARA])
    v = pagine[0]["vignette"]
    assert v[0]["personaggi"] == ["mara"] and v[1]["personaggi"] == ["mara"]
    assert v[1]["dialoghi"] == [{"chi": "mara", "testo": "C'è qualcuno?"}]


def test_archivio_ollama_per_ogni_sistema(tmp_path):
    rel = {"assets": [{"name": n} for n in ("ollama-windows-amd64.zip", "ollama-windows-arm64.zip",
                                            "ollama-darwin.tgz", "ollama-linux-amd64.tar.zst",
                                            "ollama-linux-arm64.tar.zst", "OllamaSetup.exe")]}
    assert llm.asset_ollama(rel, "Windows", "AMD64")["name"] == "ollama-windows-amd64.zip"
    assert llm.asset_ollama(rel, "Darwin", "arm64")["name"] == "ollama-darwin.tgz"
    assert llm.asset_ollama(rel, "Linux", "x86_64")["name"] == "ollama-linux-amd64.tar.zst"
    z = tmp_path / "ollama-windows-amd64.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("ollama.exe" if llm.os.name == "nt" else "ollama", b"x")
    assert llm.estrai(z, tmp_path / "a").name.startswith("ollama")
    t = tmp_path / "ollama-darwin.tgz"
    with tarfile.open(t, "w:gz") as f:
        dati = b"x"
        info = tarfile.TarInfo("bin/ollama.exe" if llm.os.name == "nt" else "bin/ollama")
        info.size = len(dati)
        f.addfile(info, io.BytesIO(dati))
    assert llm.estrai(t, tmp_path / "b").parent.name == "bin"
    assert llm._json_da_testo('<think>uhm</think>```json\n{"a": 1}\n```') == {"a": 1}


# ---------------------------------------------------------------- API con l'IA finta

def attendi(c, lid):
    for _ in range(400):
        l = next(x for x in c.get("/api/lavori").json() if x["id"] == lid)
        if l["stato"] not in ("in_coda", "in_corso"):
            return l
        time.sleep(0.02)
    raise AssertionError("il lavoro non finisce")


def risultato(stato, lid):
    return stato.gestore.lavori[lid].risultato


def prepara(casa, finto_ollama):
    archivio = Archivio(casa / "impostazioni.json")
    archivio.aggiorna(ia_url=finto_ollama.url, ia_libera_gpu=False)
    stato = App(archivio)
    return stato, TestClient(crea_app(stato, sorveglia=False))


def test_ia_stato_e_download_del_modello(casa, finto_ollama):
    stato, c = prepara(casa, finto_ollama)
    with c:
        s = c.get("/api/ia").json()
        assert s["raggiungibile"] and s["modello_presente"] and s["pronta"] and len(s["consigliati"]) == 3
        l = attendi(c, c.post("/api/ia/modello", json={"nome": "qwen3:4b"}).json()["id"])
        assert l["stato"] == "completato", l
        assert "qwen3:4b" in finto_ollama.modelli and c.get("/api/ia").json()["modello"] == "qwen3:4b"
        c.post("/api/ia/impostazioni", json={"modello": "inesistente:1b"})
        assert not c.get("/api/ia").json()["pronta"]


def test_tratti_del_personaggio_dal_testo(casa, finto_ollama):
    stato, c = prepara(casa, finto_ollama)
    with c:
        p = c.post("/api/progetti", json={"nome": "Horror"}).json()["id"]
        c.post(f"/api/progetti/{p}/personaggi", json={"nome": "Mara", "storia": "Mara ha trent'anni, capelli..."})
        assert c.get(f"/api/progetti/{p}").json()["personaggi"][0]["storia"].startswith("Mara ha")
        lid = c.post(f"/api/progetti/{p}/personaggi/mara/tratti", json={}).json()["id"]
        assert attendi(c, lid)["stato"] == "completato"
        r = risultato(stato, lid)
        assert "auburn" in r["descrizione"] and r["adulto"] is True
        chiesta = finto_ollama.richieste[-1]
        assert chiesta["keep_alive"] == 0 and chiesta["format"]["required"][0] == "genere"


def test_vignetta_dalla_descrizione_e_storia(casa, finto_ollama, finto_comfy, cartella_comfy, monkeypatch):
    stato, c = prepara(casa, finto_ollama)
    with c:
        c.post("/api/comfy/usa", json={"url": finto_comfy.url, "cartella": str(cartella_comfy)})
        p = c.post("/api/progetti", json={"nome": "Horror"}).json()["id"]
        c.post(f"/api/progetti/{p}/personaggi", json={"nome": "Mara", "trigger": "mrhunt"})
        base = f"/api/progetti/{p}/fumetto"
        f = c.get(base).json()["fumetto"]
        f["impostazioni"]["checkpoint"] = "waiIllustriousSDXL_v150.safetensors"
        f["pagine"][0]["vignette"] = [{"descrizione": "Mara corre con l'ascia contro lo zombie, sangue ovunque..."}]
        c.put(base, json=f)
        vid = c.get(base).json()["fumetto"]["pagine"][0]["vignette"][0]["id"]
        lid = c.post(f"{base}/vignette/{vid}/analizza").json()["id"]
        assert attendi(c, lid)["stato"] == "completato"
        v = c.get(base).json()["fumetto"]["pagine"][0]["vignette"][0]
        assert v["personaggi"] == ["mara"] and v["analisi"]["dati"]["frase"]
        # l'interfaccia salva senza l'analisi: resta quella del server
        f = c.get(base).json()["fumetto"]
        f["pagine"][0]["vignette"][0]["analisi"] = None
        c.put(base, json=f)
        pr = c.get(f"{base}/vignette/{vid}/prompt").json()
        assert pr["aggiornata"] and "(zombie:1.15)" in pr["prompt"]["globale"]

        # generazione: niente nuova domanda all'IA, prompt con la scena, aderenza col tagger (finto)
        class TaggerFinto:
            nomi = ["zombie", "axe", "blood splatter", "corridor"]

            def tagga(self, file):
                return {file[0].name: {"zombie": 0.8, "corridor": 0.6}}
        import app.didascalie as dd
        monkeypatch.setattr(dd, "carica_tagger", lambda *a, **k: TaggerFinto())
        prima = len(finto_ollama.richieste)
        l = attendi(c, c.post(f"{base}/genera", json={}).json()["id"])
        assert l["stato"] == "completato", l["errore"]
        assert len(finto_ollama.richieste) == prima
        versione = c.get(base).json()["immagini"][vid]["versioni"][0]
        assert "screaming" in versione["prompt"] and "zombie" in versione["prompt"]
        assert versione["aderenza"]["mancanti"] == ["axe", "blood splatter"]
        inviato = finto_comfy.ricevuti[-1]
        assert any("screaming" in n["inputs"].get("text", "") for n in inviato.values())

        # storia intera
        lid = c.post(f"{base}/storia", json={"testo": "Era notte. Mara entrò...", "sostituisci": True}).json()["id"]
        assert attendi(c, lid)["stato"] == "completato"
        vs = c.get(base).json()["fumetto"]["pagine"][0]["vignette"]
        assert [v["personaggi"] for v in vs] == [["mara"], ["mara"]] and vs[1]["formato"] == "quadrata"


def test_scena_vietata_bloccata(casa, finto_ollama):
    stato, c = prepara(casa, finto_ollama)
    scena = copy.deepcopy(SCENA)
    scena["sessuale"] = True
    scena["soggetti"][1]["adulto"] = False
    finto_ollama.scena = scena
    with c:
        p = c.post("/api/progetti", json={"nome": "X"}).json()["id"]
        c.post(f"/api/progetti/{p}/personaggi", json={"nome": "Mara"})
        base = f"/api/progetti/{p}/fumetto"
        f = c.get(base).json()["fumetto"]
        f["pagine"][0]["vignette"] = [{"descrizione": "una scena"}]
        c.put(base, json=f)
        vid = c.get(base).json()["fumetto"]["pagine"][0]["vignette"][0]["id"]
        l = attendi(c, c.post(f"{base}/vignette/{vid}/analizza").json()["id"])
        assert l["stato"] == "errore" and "non si può disattivare" in l["errore"]
        # il testo che chiede esplicitamente minori e sesso non arriva nemmeno all'IA
        f = c.get(base).json()["fumetto"]
        f["pagine"][0]["vignette"][0]["descrizione"] = "bambina nuda"
        c.put(base, json=f)
        prima = len(finto_ollama.richieste)
        l = attendi(c, c.post(f"{base}/vignette/{vid}/analizza").json()["id"])
        assert l["stato"] == "errore" and len(finto_ollama.richieste) == prima
