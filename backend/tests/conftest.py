import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from finto_comfy import FintoComfy  # noqa: E402
from finto_ollama import FintoOllama  # noqa: E402


def crea_cartella_comfy(base: Path, nome="ComfyUI", checkpoint=2, lora=3) -> Path:
    c = base / nome
    (c / "models" / "checkpoints").mkdir(parents=True)
    (c / "models" / "loras" / "personaggi").mkdir(parents=True)
    (c / "input").mkdir()
    (c / "output").mkdir()
    (c / "main.py").write_text("# finto")
    for i in range(checkpoint):
        (c / "models" / "checkpoints" / f"ck{i}.safetensors").write_bytes(b"x")
    for i in range(lora):
        (c / "models" / "loras" / "personaggi" / f"l{i}.safetensors").write_bytes(b"x")
    return c


@pytest.fixture
def cartella_comfy(tmp_path):
    return crea_cartella_comfy(tmp_path)


@pytest.fixture
def finto_comfy(cartella_comfy):
    f = FintoComfy(str(cartella_comfy)).avvia()
    yield f
    f.ferma()


@pytest.fixture
def casa(tmp_path, monkeypatch):
    """Cartella dati isolata e nessuna ricerca nelle cartelle reali dell'utente."""
    d = tmp_path / "casa"
    monkeypatch.setenv("COMIC_STUDIO_HOME", str(d))
    from app.comfy import discovery
    monkeypatch.setattr(discovery, "cartelle_tipiche", lambda: [])
    monkeypatch.setattr(discovery, "cartelle_desktop", lambda: [])
    monkeypatch.setattr(discovery, "cartelle_da_processi", lambda: [])
    monkeypatch.setattr(discovery, "PORTE", [])
    return d


@pytest.fixture
def finto_ollama():
    f = FintoOllama().avvia()
    yield f
    f.ferma()
