"""Gestione del processo di Ollama: avvio all'apertura, Avvia / Riavvia / Ferma, sorveglianza con riavvio, registro.

Si usa un `ollama` finto (finto_ollama_serve.py) messo nella cartella di Ollama portatile: è un processo vero,
che si avvia, si chiude e si blocca come farebbe Ollama.
"""
import os
import signal
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import ia as modulo_ia
from app import processo_ollama as proc
from app import rotte_testo
from app.comfy import avvio as avvio_proc
from app.main import crea_app
from app.settings import Archivio
from app.state import App
from finto_comfy import _porta_libera
from test_testo_prompt import attendi

pytestmark = pytest.mark.skipif(os.name == "nt", reason="l'ollama finto è uno script con #!")

FINTO = """#!{py}
import sys
sys.path.insert(0, {tests!r})
from finto_ollama_serve import main
main()
"""


@pytest.fixture
def ollama_finto(casa, monkeypatch):
    """Un eseguibile «ollama» finto nella cartella di Ollama portatile di Comic Studio."""
    cartella = casa / "strumenti" / "ollama" / "programma"
    cartella.mkdir(parents=True)
    exe = cartella / "ollama"
    exe.write_text(FINTO.format(py=sys.executable, tests=str(Path(__file__).parent)))
    exe.chmod(0o755)
    monkeypatch.setattr(modulo_ia, "TIMEOUT_CONTROLLO", 0.5)
    yield exe
    for p in proc.processi():                    # nessun processo rimasto acceso
        if str(exe) in " ".join(avvio_proc_cmdline(p.pid)):
            avvio_proc.ferma(p.pid)


def avvio_proc_cmdline(pid):
    import psutil
    try:
        return psutil.Process(pid).cmdline()
    except psutil.Error:
        return []


def prepara(casa, porta, **imp):
    a = Archivio(casa / "impostazioni.json")
    a.aggiorna(ia_url=f"http://127.0.0.1:{porta}", ia_libera_gpu=False, **imp)
    stato = App(a)
    return stato, TestClient(crea_app(stato, sorveglia=False))


def messaggi(stato):
    return [e["msg"] for e in stato.bus.storico]


def finche(condizione, secondi=10):
    fine = time.time() + secondi
    while time.time() < fine:
        if condizione():
            return True
        time.sleep(0.05)
    raise AssertionError("condizione mai vera")


def controlla_finche_riavvia(c, stato, giri=6):
    for _ in range(giri):
        l = c.portal.call(stato.ia.controlla)
        if l is not None:
            return l
    raise AssertionError("la sorveglianza non riavvia Ollama")


def test_avvio_sorveglianza_arresto_e_riapertura(casa, ollama_finto):
    porta = _porta_libera()
    stato, c = prepara(casa, porta)
    with c:
        s = c.get("/api/ia").json()
        assert not s["raggiungibile"] and s["eseguibile"] == str(ollama_finto) and s["portatile"]
        assert "lo sta riavviando" in s["errore"] and s["avvio_automatico"]
        # all'apertura di Comic Studio parte da solo
        c.portal.call(stato.ia.all_avvio)
        l = next(x for x in stato.gestore.lavori.values() if x.tipo == "ia_avvio")
        assert attendi(c, l.id)["stato"] == "completato", l.errore
        s = c.get("/api/ia").json()
        assert s["pronta"] and s["avviato_da_noi"] and s["pid"] and s["esterno"] is None
        pid = s["pid"]
        assert avvio_proc.leggi_pid(stato.ia.file_pid) == pid
        # il registro di Ollama va nella console, senza le richieste HTTP
        finche(lambda: any("Ollama › Listening on" in m for m in messaggi(stato)))
        assert not any("[GIN" in m or "/api/version" in m for m in messaggi(stato))
        assert any(e["livello"] == "avviso" and "no compatible GPUs" in e["msg"] for e in stato.bus.storico)

        # si chiude da solo → la sorveglianza lo riavvia (al secondo controllo)
        os.kill(pid, signal.SIGKILL)
        finche(lambda: not avvio_proc.vivo(pid))
        assert c.portal.call(stato.ia.controlla) is None
        l = controlla_finche_riavvia(c, stato)
        assert attendi(c, l.id)["stato"] == "completato", l.errore
        nuovo = c.get("/api/ia").json()
        assert nuovo["pronta"] and nuovo["pid"] != pid
        finche(lambda: any("Ollama si è chiuso" in m for m in messaggi(stato)))

        # Ferma: resta fermo, la sorveglianza non lo riaccende
        assert attendi(c, c.post("/api/ia/ollama/ferma").json()["id"])["stato"] == "completato"
        s = c.get("/api/ia").json()
        assert not s["raggiungibile"] and s["fermato"] and "premi Avvia" in s["errore"]
        assert not avvio_proc.vivo(nuovo["pid"]) and not stato.ia.file_pid.exists()
        for _ in range(4):
            assert c.portal.call(stato.ia.controlla) is None
        # Riavvia (anche da fermo) → di nuovo acceso
        assert attendi(c, c.post("/api/ia/ollama/riavvia").json()["id"])["stato"] == "completato"
        s = c.get("/api/ia").json()
        assert s["pronta"] and not s["fermato"]
        terzo = s["pid"]

    # Comic Studio si riapre (dopo una chiusura brusca): riconosce l'Ollama che aveva avviato
    stato2, c2 = prepara(casa, porta)
    with c2:
        c2.portal.call(stato2.ia.all_avvio)
        s = c2.get("/api/ia").json()
        assert s["pronta"] and s["avviato_da_noi"] and s["pid"] == terzo
        assert not any(x.tipo == "ia_avvio" for x in stato2.gestore.lavori.values())
        # chiudendo Comic Studio si chiude anche lui
        c2.portal.call(stato2.ia.ferma_ollama)
        assert not avvio_proc.vivo(terzo)


def test_bloccato_si_riavvia_ma_non_mentre_risponde(casa, ollama_finto):
    stato, c = prepara(casa, _porta_libera())
    with c:
        assert attendi(c, c.post("/api/ia/ollama/avvia").json()["id"])["stato"] == "completato"
        pid = stato.ia.pid
        (ollama_finto.parent / "modo").write_text(f"blocca:{pid}")
        # mentre l'IA sta rispondendo a una domanda lunga non lo si interrompe
        c.portal.call(stato.ia._lock.acquire)
        for _ in range(5):
            assert c.portal.call(stato.ia.controlla) is None
        c.portal.call(stato.ia._lock.release)
        l = controlla_finche_riavvia(c, stato)
        assert l.titolo == "Riavvio di Ollama"
        assert attendi(c, l.id)["stato"] == "completato", l.errore
        assert stato.ia.pid != pid and not avvio_proc.vivo(pid)
        assert any("non risponde più" in m for m in messaggi(stato))
        c.portal.call(stato.ia.ferma_ollama)


def test_avvio_fallito_spiegato_e_tentativi_limitati(casa, ollama_finto):
    (ollama_finto.parent / "modo").write_text("occupata")
    porta = _porta_libera()
    stato, c = prepara(casa, porta)
    with c:
        l = attendi(c, c.post("/api/ia/ollama/avvia").json()["id"])
        assert l["stato"] == "errore" and f"porta {porta} è già occupata" in l["errore"]
        assert stato.ia.pid is None and not stato.ia.file_pid.exists()
        for k in range(modulo_ia.TENTATIVI):
            l = controlla_finche_riavvia(c, stato)
            assert attendi(c, l.id)["stato"] == "errore"
            finche(lambda: stato.ia._fallimenti == k + 1)     # l'esito del tentativo viene contato
        for _ in range(4):
            assert c.portal.call(stato.ia.controlla) is None
        assert any(e["livello"] == "errore" and "non riparte dopo 3 tentativi" in e["msg"] for e in stato.bus.storico)
        # «Avvia» a mano ricomincia a contare
        (ollama_finto.parent / "modo").unlink()
        assert attendi(c, c.post("/api/ia/ollama/avvia").json()["id"])["stato"] == "completato"
        assert stato.ia._fallimenti == 0
        c.portal.call(stato.ia.ferma_ollama)


def test_server_openai_che_non_risponde_e_scelta_del_modello(casa, finto_ollama, monkeypatch):
    """Il caso di LM Studio impostato per sbaglio con un modello di Ollama: si suggerisce Ollama, e scegliere
    un modello dall'elenco (che è di Ollama) passa a Ollama."""
    monkeypatch.setattr(modulo_ia, "URL_OLLAMA", finto_ollama.url)
    monkeypatch.setattr(rotte_testo, "URL_OLLAMA", finto_ollama.url)
    stato, c = prepara(casa, _porta_libera(), ia_tipo="openai", ia_modello="qwen3:4b-q8_0")
    with c:
        s = c.get("/api/ia").json()
        assert not s["pronta"] and s["suggerisci_ollama"] and "Tipo → Ollama" in s["errore"]
        r = c.post("/api/ia/scegli", json={"nome": "qwen3:8b"}).json()
        assert r["lavoro"] is None and r["stato"]["tipo"] == "ollama" and r["stato"]["url"] == finto_ollama.url
        assert r["stato"]["pronta"] and r["stato"]["esterno"] == "aperto fuori da Comic Studio"
        # «Avvia» con Ollama già acceso (aperto da altri): ci si aggancia e basta
        assert attendi(c, c.post("/api/ia/ollama/avvia").json()["id"])["stato"] == "completato"
        assert stato.ia.pid is None
        # l'interruttore dell'avvio automatico
        s = c.post("/api/ia/impostazioni", json={"avvio_automatico": False}).json()
        assert s["impostazioni"]["avvio_automatico"] is False and s["avvio_automatico"] is False


def test_ollama_di_un_altro_utente(casa, monkeypatch):
    """Il servizio di sistema (utente «ollama») non si può fermare: si spiega come fare."""
    altro = proc.ProcessoOllama(4321, "ollama", 11434, mio=False)
    monkeypatch.setattr(proc, "processi", lambda porta=None: [altro])
    monkeypatch.setattr(proc, "termina", lambda lista, attesa=10: ([], lista))
    monkeypatch.setattr(proc.platform, "system", lambda: "Linux")
    stato, c = prepara(casa, _porta_libera())
    with c:
        l = attendi(c, c.post("/api/ia/ollama/riavvia").json()["id"])
        assert l["stato"] == "errore" and "sudo systemctl restart ollama" in l["errore"]
        assert stato.ia._chi_lo_ha_aperto() == "servizio di sistema (utente «ollama»)"


def test_righe_del_registro():
    assert proc._e_ollama_serve(["/usr/local/bin/ollama", "serve"])
    assert proc._e_ollama_serve(["/usr/bin/python3", "/x/ollama", "serve"])
    assert not proc._e_ollama_serve(["/usr/local/bin/ollama", "runner", "--model", "x"])
    assert proc.livello_riga('[GIN] 2026/10/26 - 10:00:00 | 200 | 1ms | 127.0.0.1 | GET "/api/version"') is None
    r = 'time=2026-10-26T10:00:00 level=ERROR source=server.go:1 msg="llama runner terminated" error="exit status 2"'
    assert proc.livello_riga(r) == "errore"
    assert proc.messaggio(r) == 'llama runner terminated (error="exit status 2")'
    assert proc.livello_riga('time=x level=WARN source=a.go:1 msg="model recommendations refresh failed"') == "debug"
    assert proc.livello_riga("Error: listen tcp 127.0.0.1:11434: bind: address already in use") == "errore"
    assert "porta 11434 è già occupata" in proc.spiega_errore(
        ["Error: listen tcp 127.0.0.1:11434: bind: address already in use"], 11434)
    assert "llama runner terminated" in proc.spiega_errore([r], 11434)
