import json
from pathlib import Path

from app.comfy import discovery
from conftest import crea_cartella_comfy


def test_riconosce_cartella(cartella_comfy, tmp_path):
    assert discovery.e_cartella_comfy(cartella_comfy)
    assert not discovery.e_cartella_comfy(tmp_path / "vuota")


def test_cartella_da_argv(tmp_path):
    main = tmp_path / "ComfyUI" / "main.py"
    assert discovery.cartella_da_argv([str(main), "--listen"]) == main.parent.resolve()
    assert discovery.cartella_da_argv(["main.py", "--base-directory", str(tmp_path)]) == tmp_path
    assert discovery.cartella_da_argv(["python", "-m", "altro"]) is None


def test_conta_modelli_anche_in_sottocartelle(cartella_comfy):
    c = discovery.conta_modelli(cartella_comfy)
    assert c["checkpoints"] == 2 and c["loras"] == 3 and c["vae"] == 0


def test_trova_istanza_in_esecuzione(casa, finto_comfy, cartella_comfy):
    trovate = discovery.cerca(url_extra=[finto_comfy.url])
    assert len(trovate) == 1
    i = trovate[0]
    assert i.cartella == str(cartella_comfy.resolve())
    assert i.url == finto_comfy.url and i.versione == "0.9.9"
    assert i.modelli["loras"] == 3


def test_portable_con_sottocartella(casa, tmp_path, monkeypatch):
    portable = tmp_path / "ComfyUI_windows_portable"
    portable.mkdir()
    (portable / "python_embeded").mkdir()
    crea_cartella_comfy(portable)
    monkeypatch.setattr(discovery, "cartelle_tipiche", lambda: [portable])
    trovate = discovery.cerca()
    assert len(trovate) == 1 and trovate[0].tipo == "portable"
    assert trovate[0].cartella.endswith("ComfyUI")


def test_config_desktop(casa, tmp_path, monkeypatch):
    base = tmp_path / "Documenti" / "ComfyUI"
    (base / "models" / "checkpoints").mkdir(parents=True)
    (base / "custom_nodes").mkdir()
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"basePath": str(base)}))
    monkeypatch.setattr(discovery, "file_config_desktop", lambda: [cfg])
    monkeypatch.undo()   # ripristina cartelle_desktop originale, poi reimposta il resto
    monkeypatch.setattr(discovery, "file_config_desktop", lambda: [cfg])
    monkeypatch.setattr(discovery, "cartelle_tipiche", lambda: [])
    monkeypatch.setattr(discovery, "cartelle_da_processi", lambda: [])
    monkeypatch.setattr(discovery, "PORTE", [])
    trovate = discovery.cerca()
    assert [t.origine for t in trovate] == ["ComfyUI Desktop"]
    assert trovate[0].codice is None


def test_nessun_duplicato(casa, finto_comfy, cartella_comfy):
    trovate = discovery.cerca(url_extra=[finto_comfy.url], cartelle_extra=[str(cartella_comfy)])
    assert len(trovate) == 1
