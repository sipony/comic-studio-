import asyncio
import threading

import pytest

from app.comfy.client import ComfyClient, ComfyErrore
from app.jobs import Bus, Gestore

WF = {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "a"}},
      "2": {"class_type": "KSampler", "inputs": {"model": ["1", 0]}},
      "3": {"class_type": "SaveImage", "inputs": {"images": ["2", 0]}}}


async def _attendi(lavoro, stati=("completato", "errore", "annullato")):
    for _ in range(200):
        if lavoro.stato in stati:
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"lavoro rimasto in {lavoro.stato}")


@pytest.mark.asyncio
async def test_lavoro_completo_con_log_da_thread():
    bus = Bus()
    bus.lega(asyncio.get_running_loop())
    q = bus.iscrivi()
    g = Gestore(bus)

    async def f(l):
        def nel_thread():
            l.log("dal thread")
            l.avanza(0.5, "metà")
        await asyncio.to_thread(nel_thread)
        return 42

    l = g.avvia("prova", "Prova", f)
    await _attendi(l)
    await asyncio.sleep(0.05)
    assert l.stato == "completato" and l.risultato == 42 and l.progresso == 1.0
    eventi = []
    while not q.empty():
        eventi.append(q.get_nowait())
    assert any(e["tipo"] == "log" and e["msg"] == "dal thread" for e in eventi)
    assert any(e["tipo"] == "avanzamento" and e["testo"] == "metà" for e in eventi)


@pytest.mark.asyncio
async def test_errore_e_annullamento():
    bus = Bus()
    bus.lega(asyncio.get_running_loop())
    g = Gestore(bus)

    async def rotto(l):
        raise ValueError("qualcosa non va")

    async def lungo(l):
        for _ in range(1000):
            l.controlla()
            await asyncio.sleep(0.01)

    a = g.avvia("x", "Rotto", rotto)
    b = g.avvia("y", "Lungo", lungo)
    await _attendi(a)
    await asyncio.sleep(0.05)
    assert g.annulla(b.id)
    await _attendi(b)
    assert a.stato == "errore" and "qualcosa non va" in a.errore
    assert b.stato == "annullato"
    assert any(e["livello"] == "errore" for e in bus.storico)


@pytest.mark.asyncio
async def test_esclusivi_uno_alla_volta():
    bus = Bus()
    bus.lega(asyncio.get_running_loop())
    g = Gestore(bus)
    in_corso, massimo = 0, 0

    async def gpu(l):
        nonlocal in_corso, massimo
        in_corso += 1
        massimo = max(massimo, in_corso)
        await asyncio.sleep(0.05)
        in_corso -= 1

    lavori = [g.avvia("g", f"G{i}", gpu, esclusivo=True) for i in range(3)]
    for l in lavori:
        await _attendi(l)
    assert massimo == 1


@pytest.mark.asyncio
async def test_client_esegue_e_segue_avanzamento(finto_comfy):
    avanzamenti = []
    async with ComfyClient(finto_comfy.url) as c:
        assert (await c.stato())["system"]["comfyui_version"] == "0.9.9"
        assert "ponyDiffusionV6XL.safetensors" in await c.modelli("checkpoints")
        uscite = await c.esegui(WF, lambda v, t: avanzamenti.append((v, t)))
        assert list(uscite) == ["3"] and uscite["3"][0]["filename"].endswith("_3.png")
        assert (await c.scarica(uscite["3"][0]))[:4] == b"\x89PNG"
    assert avanzamenti[-1][0] == 1.0
    assert any("KSampler 2/4" in t for _, t in avanzamenti)
    assert all(a[0] <= b[0] for a, b in zip(avanzamenti, avanzamenti[1:]))


@pytest.mark.asyncio
async def test_client_errori(finto_comfy):
    async with ComfyClient(finto_comfy.url) as c:
        with pytest.raises(ComfyErrore, match="Value not in list"):
            await c.esegui({"1": {"class_type": "Rotto", "inputs": {}}})
        finto_comfy.errore_nodo = "KSampler"
        with pytest.raises(ComfyErrore, match="out of memory"):
            await c.esegui(WF)
    async with ComfyClient("http://127.0.0.1:9") as c:
        with pytest.raises(ComfyErrore, match="non risponde"):
            await c.stato()
