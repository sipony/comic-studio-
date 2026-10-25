import io
import random

import pytest
from PIL import Image

from app.projects import Archivio, ErroreProgetto, ModificaPersonaggio, NuovoPersonaggio, suggerisci_trigger


@pytest.fixture
def archivio(tmp_path):
    return Archivio(tmp_path / "progetti")


def png(w=40, h=60, modo="RGB"):
    b = io.BytesIO()
    Image.new(modo, (w, h)).save(b, "PNG" if modo != "CMYK" else "JPEG")
    return b.getvalue()


def test_crea_e_id_unici(archivio):
    a = archivio.crea("La Mappa di Vetro")
    b = archivio.crea("La mappa di vetro!")
    assert a.id == "la-mappa-di-vetro" and b.id == "la-mappa-di-vetro-2"
    assert [p.id for p in archivio.elenco()] == [b.id, a.id]


def test_personaggi_e_trigger(archivio):
    p = archivio.crea("Storia")
    a = archivio.aggiungi_personaggio(p.id, NuovoPersonaggio(nome="Agente", trigger="vglcop", genere="1girl"))
    assert a.id == "agente" and a.trigger == "vglcop"
    with pytest.raises(ErroreProgetto, match="già usata"):
        archivio.aggiungi_personaggio(p.id, NuovoPersonaggio(nome="Altra", trigger="vglcop"))
    with pytest.raises(ErroreProgetto, match="conosce già"):
        archivio.aggiungi_personaggio(p.id, NuovoPersonaggio(nome="X", trigger="police"))
    with pytest.raises(ErroreProgetto, match="3-24"):
        archivio.aggiungi_personaggio(p.id, NuovoPersonaggio(nome="X", trigger="A b"))
    c = archivio.aggiungi_personaggio(p.id, NuovoPersonaggio(nome="Commissario Rossi", genere="1boy"))
    assert c.trigger and c.trigger != a.trigger
    m = archivio.modifica_personaggio(p.id, c.id, ModificaPersonaggio(descrizione="old man, white mustache"))
    assert m.descrizione == "old man, white mustache" and m.trigger == c.trigger
    with pytest.raises(ErroreProgetto):
        archivio.modifica_personaggio(p.id, c.id, ModificaPersonaggio(trigger="vglcop"))


def test_suggerimento_trigger_valido():
    rng = random.Random(1)
    for nome in ["Agente", "Commissario", "Al", "Émilie", "123", "x"]:
        t = suggerisci_trigger(nome, rng=rng)
        assert 3 <= len(t) <= 24 and t[0].isalpha() and t.islower()


def test_riferimento(archivio):
    p = archivio.crea("Storia")
    c = archivio.aggiungi_personaggio(p.id, NuovoPersonaggio(nome="Agente"))
    with pytest.raises(ErroreProgetto):
        archivio.file_riferimento(p.id, c.id)
    archivio.salva_riferimento(p.id, c.id, png(modo="P"))
    f = archivio.file_riferimento(p.id, c.id)
    assert Image.open(f).size == (40, 60)
    with pytest.raises(ErroreProgetto, match="non è un'immagine"):
        archivio.salva_riferimento(p.id, c.id, b"ciao")


def test_eliminazione_va_nel_cestino(archivio):
    p = archivio.crea("Da buttare")
    c = archivio.aggiungi_personaggio(p.id, NuovoPersonaggio(nome="Tizio"))
    archivio.elimina_personaggio(p.id, c.id)
    archivio.elimina(p.id)
    assert archivio.elenco() == []
    assert len(list((archivio.radice / ".cestino").iterdir())) == 2


def test_id_non_validi(archivio):
    with pytest.raises(ErroreProgetto):
        archivio.leggi("../fuori")
    with pytest.raises(ErroreProgetto):
        archivio.cartella_personaggio("ok", "../../x")
