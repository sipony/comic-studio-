"""Scelta del modello dell'IA locale: tag e quantizzazioni, valutazione per l'hardware, registro (finto), API."""
import asyncio

import pytest

from app import catalogo_ia as cat
from finto_registro import FintoRegistro
from test_testo_prompt import attendi, prepara

RTX_3060 = cat.Hardware("RTX 3060", 12, 32)
RTX_4060 = cat.Hardware("RTX 4060", 8, 16)
SOLO_CPU = cat.Hardware(None, 0, 16)
MAC = cat.Hardware("Apple Silicon", 0, 36, apple=True)


def migliore(r):
    return next(v for v in r["varianti"] if v["nome"] == r["migliore"])


def test_tag_quantizzazioni_e_parametri():
    assert cat.leggi_tag("8b-q4_K_M") == ("8b", "q4_K_M")
    assert cat.leggi_tag("12b-it-qat") == ("12b", "qat")
    assert cat.leggi_tag("24b-instruct-2506-q8_0") == ("24b", "q8_0")
    assert cat.leggi_tag("8b") == ("8b", None) and cat.leggi_tag("30b-a3b") == ("30b-a3b", None)
    # modelli base, versioni nel cloud e alias come latest non si propongono
    for t in ("latest", "7b-text-q4_0", "12b-pt-q4_K_M", "20b-cloud", "nomic"):
        assert cat.leggi_tag(t) is None, t
    assert cat.parametri("30b-a3b") == (30.0, 3.0) and cat.parametri("0.6b") == (0.6, None)
    assert cat.parametri("135m") == (0.135, None)
    # la stima della dimensione segue i bit della quantizzazione
    assert cat.stima_byte(8, "q4_K_M") < cat.stima_byte(8, "q8_0") < cat.stima_byte(8, "fp16")


def test_valutazione_per_l_hardware():
    v = cat.valuta(14, None, 9_000_000_000, "q4_K_M", 3, RTX_3060)
    assert v["dove"] == "gpu" and v["memoria_gb"] > 9
    assert cat.valuta(32, None, 20_000_000_000, "q4_K_M", 3, RTX_3060)["dove"] == "misto"
    assert cat.valuta(70, None, 43_000_000_000, "q4_K_M", 3, RTX_4060)["dove"] == "troppo"
    assert cat.valuta(8, None, 5_000_000_000, "q4_K_M", 3, SOLO_CPU)["dove"] == "cpu"
    assert cat.valuta(32, None, 20_000_000_000, "q4_K_M", 3, MAC)["dove"] == "gpu"      # memoria unificata
    # un MoE in parte sulla CPU perde meno di un modello denso della stessa dimensione
    moe = cat.valuta(30, 3, 18_500_000_000, "q4_K_M", 3, RTX_3060)
    denso = cat.valuta(32, None, 20_000_000_000, "q4_K_M", 3, RTX_3060)
    assert moe["dove"] == denso["dove"] == "misto" and moe["punteggio"] > denso["punteggio"]


def test_catalogo_ordinato_per_il_computer(casa):
    inst = [{"name": "qwen3:8b", "size": 5_225_373_696,
             "details": {"parameter_size": "8.2B", "quantization_level": "Q4_K_M"}},
            {"name": "deepseek-r1:7b", "size": 4_700_000_000,
             "details": {"parameter_size": "7.6B", "quantization_level": "Q4_K_M"}}]
    r = cat.costruisci(RTX_3060, inst, "qwen3:8b")
    assert not r["online"] and r["da_aggiornare"] and r["hardware"]["memoria_gpu"] == 11.5
    righe = r["modelli"]
    # i primi tre sono consigliati e stanno tutti sulla GPU; i più adatti a 12 GB sono attorno ai 12-14 miliardi
    assert [x.get("consigliato") for x in righe[:4]] == [True, True, True, None]
    assert all(x["dove"] == "gpu" for x in righe[:3]) and righe[0]["migliore_in_assoluto"]
    assert 8 <= righe[0]["parametri"] <= 14
    # quelli che non entrano stanno in fondo ma si vedono comunque
    assert righe[-1]["dove"] == "troppo" and len(righe) > 20
    # il modello già scaricato viene riconosciuto anche con il nome corto (alias della q4_K_M)
    q8 = next(x for x in righe if x["famiglia"] == "qwen3" and x["dimensione"] == "8B")
    v = next(v for v in q8["varianti"] if v["installato"])
    assert v["nome"] == "qwen3:8b" and v["attuale"] and "qwen3:8b-q4_K_M" in v["alias"] and not v["stimata"]
    # senza rete la quantizzazione predefinita si scarica con il tag corto, che esiste sempre
    g12 = next(x for x in righe if x["famiglia"] == "gemma3" and x["dimensione"] == "12B")
    assert {v["nome"] for v in g12["varianti"]} >= {"gemma3:12b", "gemma3:12b-it-qat", "gemma3:12b-it-q8_0"}
    assert {x["quant"] for x in q8["varianti"]} == {"Q4_K_M", "Q8_0", "FP16"}
    # un modello scaricato a mano che non è nel catalogo compare lo stesso
    assert any(x["migliore"] == "deepseek-r1:7b" and x["varianti"][0]["installato"] for x in righe)
    # senza GPU vincono i modelli più piccoli
    cpu = cat.costruisci(SOLO_CPU, [], None)["modelli"]
    assert all(migliore(x)["gb"] < 9 for x in cpu[:3]) and all(x["dove"] == "cpu" for x in cpu[:3])


@pytest.fixture
def registro(monkeypatch):
    f = FintoRegistro().avvia()
    monkeypatch.setattr(cat, "REGISTRO", f.url)
    monkeypatch.setattr(cat, "SITO", f.url)
    yield f
    f.ferma()


def test_elenco_online_dal_registro_e_dal_sito(casa, registro):
    r = asyncio.run(cat.aggiorna_online(["qwen3", "gemma3", "inesistente"], lambda *_: None, lambda: False))
    assert r["aggiornate"] == ["qwen3", "gemma3"] and "inesistente" in r["errori"]
    c = cat.costruisci(RTX_3060, [], "qwen3:8b")
    assert c["online"] and not c["da_aggiornare"]
    qwen = {x["dimensione"]: x for x in c["modelli"] if x["famiglia"] == "qwen3"}
    assert set(qwen) == {"8B", "14B", "32B", "30B-A3B", "235B-A22B"}           # latest non è una dimensione
    q4 = next(v for v in qwen["8B"]["varianti"] if v["quant"] == "Q4_K_M")
    assert q4["gb"] == 5.23 and not q4["stimata"] and "qwen3:8b" in q4["alias"]  # stesso file del tag corto
    assert qwen["235B-A22B"]["dove"] == "troppo"
    # gemma3: tag letti dalla pagina del sito, il modello base (pt) è escluso
    gemma = {x["dimensione"]: x for x in c["modelli"] if x["famiglia"] == "gemma3"}
    assert {v["quant"] for v in gemma["12B"]["varianti"]} == {"Q4_K_M", "QAT (4 bit)"}
    assert "gemma3:12b" in next(v for v in gemma["12B"]["varianti"] if v["quant"] == "Q4_K_M")["alias"]
    # le famiglie non aggiornate restano con la stima
    assert any(x["famiglia"] == "phi4" and x["varianti"][0]["stimata"] for x in c["modelli"])


def test_api_catalogo_scelta_e_installazione(casa, finto_ollama, registro, monkeypatch):
    monkeypatch.setattr(cat, "leggi_hardware", lambda _d: RTX_3060)
    stato, c = prepara(casa, finto_ollama)
    with c:
        r = c.get("/api/ia/catalogo").json()
        assert r["stato"]["pronta"] and r["hardware"]["gpu"] == "RTX 3060" and r["modelli"][0]["consigliato"]
        # un modello che non c'è nell'elenco: si cercano le sue versioni nel registro
        l = attendi(c, c.post("/api/ia/catalogo/aggiorna", json={"famiglia": "nuovo-modello"}).json()["id"])
        assert l["stato"] == "completato", l
        r = c.get("/api/ia/catalogo").json()
        nuovo = next(x for x in r["modelli"] if x["famiglia"] == "nuovo-modello")
        assert {v["quant"] for v in nuovo["varianti"]} == {"Q4_K_M", "Q6_K"} and "nuovo-modello" in r["famiglie"]
        # scegliere un modello non scaricato lo scarica e lo imposta
        s = c.post("/api/ia/scegli", json={"nome": "nuovo-modello:7b-q6_K"}).json()
        assert s["lavoro"] and not s["stato"]["pronta"]
        assert attendi(c, s["lavoro"]["id"])["stato"] == "completato"
        assert c.get("/api/ia").json()["pronta"] and "nuovo-modello:7b-q6_K" in finto_ollama.modelli
        # uno già scaricato si usa subito
        s = c.post("/api/ia/scegli", json={"nome": "qwen3:8b"}).json()
        assert s["lavoro"] is None and s["stato"]["pronta"] and s["stato"]["modello"] == "qwen3:8b"
        # dall'IA disattivata: scegliere un modello riattiva Ollama
        c.post("/api/ia/impostazioni", json={"tipo": "nessuna"})
        s = c.post("/api/ia/scegli", json={"nome": "qwen3:8b"}).json()
        assert s["stato"]["tipo"] == "ollama"
        assert c.post("/api/ia/catalogo/aggiorna", json={"famiglia": "../x"}).status_code == 422


def test_lavoro_fallito_perche_manca_il_modello(casa, finto_ollama):
    stato, c = prepara(casa, finto_ollama)
    with c:
        p = c.post("/api/progetti", json={"nome": "Horror"}).json()["id"]
        c.post(f"/api/progetti/{p}/personaggi", json={"nome": "Mara", "storia": "Mara ha trent'anni"})
        c.post("/api/ia/impostazioni", json={"modello": "gemma3:12b"})
        l = attendi(c, c.post(f"/api/progetti/{p}/personaggi/mara/tratti", json={}).json()["id"])
        # l'interfaccia riconosce il codice e apre la finestra per scegliere e scaricare il modello
        assert l["stato"] == "errore" and l["codice"] == "ia_non_pronta" and "gemma3:12b" in l["errore"]
        c.post("/api/ia/impostazioni", json={"tipo": "nessuna"})
        l = attendi(c, c.post(f"/api/progetti/{p}/personaggi/mara/tratti", json={}).json()["id"])
        assert l["codice"] == "ia_non_pronta"
        # gli altri errori non hanno il codice
        c.post("/api/ia/impostazioni", json={"tipo": "ollama", "url": finto_ollama.url, "modello": "qwen3:8b"})
        finto_ollama.scena = {"rotta": True}
        lid = c.post("/api/ia/prova", json={"testo": "una scena"}).json()["id"]
        assert attendi(c, lid)["codice"] is None
