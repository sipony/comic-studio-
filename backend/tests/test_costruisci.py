"""Parti dello script degli installer che si possono provare senza scaricare niente."""
import importlib.util
import os
import stat
import sys
import zipfile
from pathlib import Path

import pytest

FILE = Path(__file__).resolve().parents[2] / "installer" / "costruisci.py"
spec = importlib.util.spec_from_file_location("costruisci", FILE)
costruisci = importlib.util.module_from_spec(spec)
sys.modules["costruisci"] = costruisci
spec.loader.exec_module(costruisci)


@pytest.mark.skipif(os.name == "nt", reason="collegamenti simbolici")
def test_zip_mac_conserva_permessi_e_collegamenti(tmp_path):
    app = tmp_path / "Comic Studio.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    eseg = app / "Contents" / "MacOS" / "ComicStudio"
    eseg.write_text("#!/bin/bash\n")
    eseg.chmod(0o755)
    (app / "Contents" / "python3.12").write_text("x")
    (app / "Contents" / "python3").symlink_to("python3.12")
    z = tmp_path / "app.zip"
    costruisci.zip_con_permessi(app, z)
    with zipfile.ZipFile(z) as f:
        info = {i.filename: i for i in f.infolist()}
        assert info["Comic Studio.app/Contents/MacOS/ComicStudio"].external_attr >> 16 & 0o111
        link = info["Comic Studio.app/Contents/python3"]
        assert stat.S_ISLNK(link.external_attr >> 16) and f.read(link) == b"python3.12"


def test_modelli_dei_pacchetti():
    nsi = costruisci.NSI.format(versione="0.7.0", versione4="0.7.0.0", uscita="x.exe", icona="i.ico",
                                radice="r", dimensione=1)
    assert 'RequestExecutionLevel user' in nsi and "pythonw.exe" in nsi and "{" not in nsi.replace("${", "")
    compile(costruisci.CHIUDI, "chiudi.py", "exec")
    compile(costruisci.LANCIATORE, "comic_studio.pyw", "exec")
    assert costruisci.versione().count(".") == 2
    assert set(costruisci.PACCHETTI.values()) <= set(costruisci.BERSAGLI)
