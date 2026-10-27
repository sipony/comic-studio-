import io
import shutil
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import addestramento as ad
from app import rotte_addestramento, rotte_dataset
from app.dataset import ArchivioDataset, InfoImmagine
from app.main import crea_app
from app.settings import Archivio
from app.somiglianza import ValutatoreSemplice
from app.state import App

QUI = Path(__file__).parent


def test_parametri_e_comando(tmp_path):
    c = ad.preset("8gb")
    assert c.fp8 and c.rank == 16 and c.ottimizzatore == "Adafactor"
    assert ad.ripetizioni(c, 30) == 7 and ad.passi_totali(c, 30) == 30 * 7 * 10
    k = ad.Kohya(tmp_path, tmp_path / "py")
    a = ad.argomenti(k, c, Path("/m/ck.safetensors"), tmp_path / "d.toml", tmp_path / "out", "vglcop")
    assert "--fp8_base" in a and "--network_train_unet_only" in a and "--cache_text_encoder_outputs" in a
    assert a[a.index("--network_dim") + 1] == "16" and "scale_parameter=False" in a
    q = ad.preset("qualita")
    a = ad.argomenti(k, q, Path("/m/ck.safetensors"), tmp_path / "d.toml", tmp_path / "out", "vglcop")
    assert "--text_encoder_lr" in a and "--network_train_unet_only" not in a and "--fp8_base" not in a
    m = c.model_copy(update={"mescola_didascalie": True, "argomenti_extra": "--max_grad_norm 1.0"})
    a = ad.argomenti(k, m, Path("/m/ck.safetensors"), tmp_path / "d.toml", tmp_path / "out", "vglcop")
    assert "--cache_text_encoder_outputs" not in a and a[-2:] == ["--max_grad_norm", "1.0"]
    toml = ad.toml_dataset(tmp_path / "ds", m, 30)
    assert "shuffle_caption = true" in toml and "keep_tokens = 1" in toml and "num_repeats = 7" in toml


def test_preset_per_vram():
    g = 1024 ** 3
    assert ad.preset_per_vram(8 * g) == "8gb" and ad.preset_per_vram(12 * g) == "equilibrato"
    assert ad.preset_per_vram(24 * g) == "qualita" and ad.preset_per_vram(None) == "8gb"


def test_lettura_uscita_kohya():
    av = ad.Avanzamento()
    assert ad.leggi_riga("steps:  12%|█▎        | 240/2000 [03:20<24:30,  1.20it/s, avr_loss=0.0812]", av)
    assert (av.passo, av.totale, av.rimanente, av.loss) == (240, 2000, "24:30", 0.0812)
    assert av.velocita == "1.20 it/s"
    ad.leggi_riga("steps:  50%|█████     | 1000/2000 [20:00<20:00,  1.67s/it, avr_loss=6.1e-02]", av)
    assert av.velocita == "1.67 s/it" and av.loss == 0.061
    ad.leggi_riga("epoch 3/10", av)
    assert (av.epoca, av.epoche) == (3, 10)
    ad.leggi_riga("saving checkpoint: C:\\x\\vglcop-000003.safetensors", av)
    assert av.salvato.endswith("vglcop-000003.safetensors")
    assert not ad.leggi_riga("caching latents...", ad.Avanzamento())
    assert "Memoria" in ad.spiega_errore("torch.OutOfMemoryError: CUDA out of memory")
    assert "bitsandbytes" in ad.spiega_errore("ModuleNotFoundError: No module named 'bitsandbytes'")


def test_epoche(tmp_path):
    for n in (1, 2, 3):
        (tmp_path / f"vglcop-{n:06d}.safetensors").write_bytes(b"x")
    (tmp_path / "vglcop.safetensors").write_bytes(b"x")
    (tmp_path / "altro-000001.safetensors").write_bytes(b"x")
    e = ad.file_epoche(tmp_path, "vglcop")
    assert [x["epoca"] for x in e] == [1, 2, 3, 4] and e[-1]["ultima"]
    assert ad.epoche_da_provare(list(range(1, 11))) == [5, 6, 8, 10]
    assert ad.epoche_da_provare([1, 2]) == [1, 2]


def test_comandi_installazione(tmp_path):
    p = ad.comandi_installazione(tmp_path / "k", ["py", "-3.10"], "cuda", git=True)
    assert p[0][1][:2] == ["git", "clone"] and p[1][1][:2] == ["py", "-3.10"]
    torch = next(c for d, c, _ in p if "PyTorch" in d)
    assert "torch==2.6.0" in torch and ad.INDICE_CUDA in torch
    mac = next(c for d, c, _ in ad.comandi_installazione(tmp_path / "k", ["python3"], "mps", git=False) if "PyTorch" in d)
    assert "--index-url" not in mac


def png(c):
    b = io.BytesIO()
    Image.new("RGB", (64, 96), c).save(b, "PNG")
    return b.getvalue()


@pytest.fixture
def ambiente(casa, finto_comfy, cartella_comfy, monkeypatch, tmp_path):
    kohya = tmp_path / "kohya"
    kohya.mkdir()
    shutil.copy(QUI / "finto_kohya.py", kohya / "sdxl_train_network.py")
    monkeypatch.setattr(ad, "trova_kohya", lambda dati: ad.Kohya(kohya, Path(sys.executable)))
    monkeypatch.setattr(rotte_addestramento, "valutatore", lambda *a, **k: ValutatoreSemplice())
    monkeypatch.setattr(rotte_dataset, "valutatore", lambda *a, **k: ValutatoreSemplice())
    stato = App(Archivio(casa / "impostazioni.json"))
    c = TestClient(crea_app(stato, sorveglia=False))
    with c:
        c.post("/api/comfy/usa", json={"url": finto_comfy.url, "cartella": str(cartella_comfy)})
        p = c.post("/api/progetti", json={"nome": "Prova"}).json()["id"]
        c.post(f"/api/progetti/{p}/personaggi", json={"nome": "Agente", "trigger": "vglcop"})
        c.put(f"/api/progetti/{p}/personaggi/agente/riferimento", files={"file": ("r.png", png((200, 10, 10)), "image/png")})
        ds = ArchivioDataset(stato.progetti)
        for n in range(1, 7):
            ds.aggiungi_immagine(p, "agente", png((200, n * 30, 10)),
                                 InfoImmagine(file=f"{n:04d}.png", numero=n, variante="upper body", stato="tenuta"))
        yield c, p, stato, cartella_comfy


def attendi(c, lid):
    for _ in range(600):
        l = next(x for x in c.get("/api/lavori").json() if x["id"] == lid)
        if l["stato"] not in ("in_coda", "in_corso"):
            return l
        time.sleep(0.02)
    raise AssertionError("lavoro bloccato")


def test_flusso_addestramento(ambiente, monkeypatch, finto_comfy):
    c, p, stato, comfy = ambiente
    base = f"/api/progetti/{p}/personaggi/agente/addestramento"
    r = c.get(base).json()
    assert r["immagini"] == 6 and r["preset_consigliato"] == "8gb" and r["epoche"] == []
    r = c.post(f"{base}/avvia")
    assert r.status_code == 400 and "checkpoint" in r.json()["detail"]
    cfg = c.get(base).json()["config"]
    cfg.update(checkpoint="ck0.safetensors", epoche=4)
    r = c.put(f"{base}/config", json=cfg).json()
    assert r["passi_totali"] == 6 * r["ripetizioni"] * 4
    r = c.post(f"{base}/preset", json={"preset": "equilibrato"}).json()
    assert r["config"]["rank"] == 32 and r["config"]["epoche"] == 4 and r["config"]["checkpoint"] == "ck0.safetensors"

    l = attendi(c, c.post(f"{base}/avvia").json()["id"])
    assert l["stato"] == "completato", l["errore"]
    r = c.get(base).json()
    assert [e["epoca"] for e in r["epoche"]] == [1, 2, 3, 4]
    assert len(r["loss"]) >= 10 and r["loss"][0][1] > r["loss"][-1][1]
    assert r["stato"]["ultimo_esito"] == "completato"
    # a fine addestramento il LoRA c'è già: l'ultima epoca, versione 1, in uso
    assert [(v["versione"], v["epoca"], v["automatica"], v["in_uso"], v["esiste"]) for v in r["storico"]] == \
        [(1, 4, True, True, True)]
    assert r["stato"]["lora_finale"] == "comic_studio/vglcop_v1.safetensors"
    assert r["stato"]["addestramenti"][-1]["esito"] == "completato"
    assert r["stato"]["addestramenti"][-1]["parametri"]["rank"] == 32
    cartella = stato.progetti.cartella_personaggio(p, "agente") / "addestramento"
    assert sorted(f.name for f in (cartella / "dataset").iterdir())[:2] == ["0001.png", "0001.txt"]
    assert "--dataset_config" in (cartella / "comando.txt").read_text()
    log = [x["msg"] for x in c.get("/api/log").json()]
    assert any("Salvata l'epoca" in m for m in log) and not any("steps:" in m for m in log)

    # la prova usa lo stesso disegno del dataset: LoRA e tag di stile delle proposte da cui è nato il personaggio
    from app.projects import ModificaPersonaggio
    stato.progetti.modifica_personaggio(p, "agente", ModificaPersonaggio(origine={
        "checkpoint": "ck0.safetensors", "lora_stile": "KonicsXL_Style.safetensors", "forza_lora": 0.8,
        "stile": "western comics (style)"}))
    l = attendi(c, c.post(f"{base}/prova", json={"epoche": [2, 4]}).json()["id"])
    assert l["stato"] == "completato", l["errore"]
    w = finto_comfy.ricevuti[-1]
    assert w["9"]["inputs"]["lora_name"] == "KonicsXL_Style.safetensors" and w["2"]["inputs"]["model"] == ["9", 0]
    assert w["3"]["inputs"]["text"].endswith("western comics (style)") and "vglcop" in w["3"]["inputs"]["text"]
    test = c.get(base).json()["stato"]["test"]
    assert set(test) == {"2", "4"} and len(test["2"]["immagini"]) == 3 and test["2"]["punteggio"] is not None
    assert c.get(f"{base}/test/{test['2']['immagini'][0]}").headers["content-type"] == "image/png"
    assert (comfy / "models" / "loras" / "comic_studio" / "test_vglcop-002.safetensors").exists()

    s = c.post(f"{base}/scegli", json={"epoca": 2}).json()
    assert s["lora_finale"] == "comic_studio/vglcop_v2.safetensors" and s["epoca_finale"] == 2
    loras = comfy / "models" / "loras" / "comic_studio"
    assert (loras / "vglcop_v2.safetensors").exists() and (loras / "vglcop_v1.safetensors").exists()
    assert not list(loras.glob("test_*"))
    r = c.get(base).json()
    assert [(v["versione"], v["in_uso"]) for v in r["storico"]] == [(2, True), (1, False)]
    assert r["storico"][0]["punteggio"] is not None
    # si torna alla versione 1; quella in uso non si elimina; la 2 va nel cestino
    assert c.delete(f"{base}/storico/2").status_code == 409
    r = c.post(f"{base}/storico/1/usa").json()
    assert r["stato"]["lora_finale"] == "comic_studio/vglcop_v1.safetensors" and r["stato"]["epoca_finale"] == 4
    r = c.delete(f"{base}/storico/2").json()
    assert [v["versione"] for v in r["storico"]] == [1] and not (loras / "vglcop_v2.safetensors").exists()

    s = c.post(f"{base}/esistente", json={"lora": "altro/mio.safetensors"}).json()
    assert s["origine"] == "esistente" and s["lora_finale"] == "altro/mio.safetensors"

    # secondo addestramento con errore di memoria: messaggio chiaro, epoche vecchie nel cestino
    monkeypatch.setenv("FINTO_KOHYA_ERRORE", "oom")
    l = attendi(c, c.post(f"{base}/avvia").json()["id"])
    assert l["stato"] == "errore" and "Memoria della scheda video" in l["errore"]
    r = c.get(base).json()
    assert r["epoche"] == [] and r["stato"]["addestramenti"][-1]["esito"] == "errore"
    assert [v["versione"] for v in r["storico"]] == [1]                  # lo storico resta


def test_senza_kohya(casa, monkeypatch):
    monkeypatch.setattr(ad, "trova_kohya", lambda dati: None)
    c = TestClient(crea_app(App(Archivio(casa / "impostazioni.json")), sorveglia=False))
    with c:
        assert c.get("/api/kohya").json()["installato"] is False
        p = c.post("/api/progetti", json={"nome": "X"}).json()["id"]
        c.post(f"/api/progetti/{p}/personaggi", json={"nome": "Agente", "trigger": "vglcop"})
        r = c.post(f"/api/progetti/{p}/personaggi/agente/addestramento/avvia")
        assert r.status_code == 409 and "kohya" in r.json()["detail"]


@pytest.mark.asyncio
async def test_lettura_processo_anche_in_thread(tmp_path):
    from collections import deque
    import asyncio
    script = tmp_path / "s.py"
    script.write_text("import sys\nsys.stdout.write('uno\\rdue\\ntre')\n")
    for funzione in ("asyncio", "thread"):
        righe, coda = [], deque(maxlen=10)
        if funzione == "thread":
            codice = await rotte_addestramento._esegui_in_thread([sys.executable, str(script)], None, None, righe.append, coda)
        else:
            from app.jobs import Bus, Gestore
            bus = Bus()
            bus.lega(asyncio.get_running_loop())
            l = Gestore(bus).avvia("x", "x", lambda l: asyncio.sleep(0))
            codice = await rotte_addestramento.esegui_processo([sys.executable, str(script)], None, l, righe.append, coda)
        await asyncio.sleep(0.05)
        assert codice == 0 and righe == ["uno", "due", "tre"], funzione


def test_prompt_di_prova_e_preset_8gb(tmp_path):
    """La trigger word e il genere davanti ai prompt di prova se mancano; l'italiano si segnala; il preset «8 GB»
    impara abbastanza (Adafactor a 4e-4) anche nelle configurazioni salvate prima."""
    from types import SimpleNamespace
    from app.rotte_addestramento import non_inglese, prompt_di_prova
    p = SimpleNamespace(trigger="scrtrxj", genere="1girl")
    assert prompt_di_prova("sitting, smile", p) == "{trigger}, {genere}, sitting, smile"
    assert prompt_di_prova("{trigger}, {genere}, solo", p) == "{trigger}, {genere}, solo"
    assert prompt_di_prova("scrtrxj, 1girl, solo", p) == "scrtrxj, 1girl, solo"
    assert non_inglese("scrtrxj seduta su una sedia con il cappello") and not non_inglese("{trigger}, sitting, smile")
    assert ad.preset("8gb").learning_rate == 4e-4
    a = ad.ArchivioAddestramento.__new__(ad.ArchivioAddestramento)
    vecchia = ad.ConfigAddestramento(preset="8gb", learning_rate=1e-4)
    f = tmp_path / "config.json"
    f.write_text(vecchia.model_dump_json())
    a.cartella = lambda pid, cid: tmp_path
    assert a.config("p", "c").learning_rate == 4e-4
