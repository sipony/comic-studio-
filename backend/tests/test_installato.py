"""Avvio da installer (senza terminale) e chiusura dall'interfaccia."""
import sys
import time

from fastapi.testclient import TestClient

from app import __main__ as principale, installato
from app.main import crea_app
from app.settings import Archivio
from app.state import App


def test_esci_dall_interfaccia(casa):
    api = crea_app(App(Archivio(casa / "impostazioni.json")), sorveglia=False)
    with TestClient(api) as c:
        assert c.post("/api/esci", json={}).status_code == 409      # nessuno sa come spegnere il server
        chiamate = []
        api.state.spegni = lambda: chiamate.append(1)
        assert c.post("/api/esci", json={"comfy": False}).json()["ok"]
        time.sleep(0.8)
        assert chiamate == [1]
        assert any(e["msg"] == "Comic Studio si chiude" for e in api.state.app.bus.storico)


def test_avvio_installato_usa_la_porta_libera_e_scrive_il_registro(casa, monkeypatch):
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    occupate = {8765}
    monkeypatch.setattr(principale, "porta_libera", lambda h, p: p not in occupate)
    monkeypatch.setattr(principale, "e_comic_studio", lambda p: False)       # la 8765 è di un altro programma
    servite = []
    monkeypatch.setattr(principale, "servi", lambda h, p, apri_browser: servite.append((h, p, apri_browser)))
    installato.main()
    sys.stdout.flush()
    assert servite == [("127.0.0.1", 8766, True)]
    testo = (casa / "comicstudio.log").read_text(encoding="utf-8")
    assert "Comic Studio su http://127.0.0.1:8766" in testo


def test_se_e_gia_aperto_apre_solo_il_browser(casa, monkeypatch):
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(principale, "porta_libera", lambda h, p: False)
    monkeypatch.setattr(principale, "e_comic_studio", lambda p: p == 8765)
    monkeypatch.setattr(principale, "servi", lambda *a, **k: (_ for _ in ()).throw(AssertionError("non deve partire")))
    aperti = []
    monkeypatch.setattr(installato.webbrowser, "open", aperti.append)
    installato.main()
    assert aperti == ["http://127.0.0.1:8765"]


def test_errore_all_avvio_mostra_un_messaggio(casa, monkeypatch):
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(principale, "porta_libera", lambda h, p: True)
    monkeypatch.setattr(principale, "servi", lambda *a, **k: (_ for _ in ()).throw(OSError("disco pieno")))
    messaggi = []
    monkeypatch.setattr(installato, "messaggio", messaggi.append)
    try:
        installato.main()
    except SystemExit as e:
        assert e.code == 1
    assert "disco pieno" in messaggi[0] and "comicstudio.log" in messaggi[0]


def test_appimage_si_aggiunge_al_menu(tmp_path, monkeypatch):
    appdir = tmp_path / "AppDir"
    appdir.mkdir()
    (appdir / "comic-studio.png").write_bytes(b"png")
    monkeypatch.setenv("APPIMAGE", str(tmp_path / "ComicStudio.AppImage"))
    monkeypatch.setenv("APPDIR", str(appdir))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    installato.integra_menu_linux()
    voce = (tmp_path / "share" / "applications" / "comic-studio.desktop").read_text()
    assert f'Exec="{tmp_path / "ComicStudio.AppImage"}"' in voce and "Terminal=false" in voce
    assert (tmp_path / "share" / "icons" / "hicolor" / "256x256" / "apps" / "comic-studio.png").exists()


def _prepara_aperto(monkeypatch, versione, attivi=0):
    """Sulla 8765 c'è già Comic Studio `versione` con `attivi` lavori in corso."""
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    stato = {"aperto": True, "chiuso": 0}
    monkeypatch.setattr(principale, "porta_libera", lambda h, p: not (p == 8765 and stato["aperto"]))
    monkeypatch.setattr(principale, "e_comic_studio", lambda p: p == 8765 and stato["aperto"])
    monkeypatch.setattr(installato, "info_aperto", lambda p: {"versione": versione, "attivi": attivi,
                                                             "titoli": ["Dataset di comandante: 100 immagini"] * attivi})

    def chiudi(p, attesa=30):
        stato["aperto"] = False
        stato["chiuso"] += 1
        return True
    monkeypatch.setattr(installato, "chiudi_aperto", chiudi)
    servite, aperti = [], []
    monkeypatch.setattr(principale, "servi", lambda h, p, apri_browser: servite.append(p))
    monkeypatch.setattr(installato.webbrowser, "open", aperti.append)
    return stato, servite, aperti


def test_versione_vecchia_aperta_viene_sostituita(casa, monkeypatch):
    stato, servite, aperti = _prepara_aperto(monkeypatch, "0.17.0")
    installato.main()
    assert stato["chiuso"] == 1 and servite == [8765] and not aperti
    assert "lo chiudo per avviare la versione" in (casa / "comicstudio.log").read_text(encoding="utf-8")


def test_stessa_versione_apre_solo_il_browser(casa, monkeypatch):
    from app import __version__
    stato, servite, aperti = _prepara_aperto(monkeypatch, __version__)
    installato.main()
    assert stato["chiuso"] == 0 and not servite and aperti == ["http://127.0.0.1:8765"]


def test_con_lavori_in_corso_prima_chiede(casa, monkeypatch):
    domande = []
    monkeypatch.setattr(installato, "chiedi", lambda t: domande.append(t) or False)
    stato, servite, aperti = _prepara_aperto(monkeypatch, "0.17.0", attivi=1)
    installato.main()
    assert "Dataset di comandante" in domande[0] and "0.17.0" in domande[0]
    assert stato["chiuso"] == 0 and not servite and aperti == ["http://127.0.0.1:8765"]
    # risposta «Sostituisci»
    monkeypatch.setattr(installato, "chiedi", lambda t: True)
    stato, servite, aperti = _prepara_aperto(monkeypatch, "0.17.0", attivi=1)
    installato.main()
    assert stato["chiuso"] == 1 and servite == [8765]
