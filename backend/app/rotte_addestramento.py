"""API e lavori dello Step 3 (Addestramento): installazione di kohya, parametri, addestramento, test e scelta."""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
import time
import zipfile
from collections import deque
from pathlib import Path

import httpx
import numpy as np
import psutil
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import addestramento as ad
from .comfy.client import ComfyErrore
from .dataset import ArchivioDataset, componi, tag_qualita
from .didascalie import ArchivioDidascalie
from .jobs import Lavoro
from .projects import ErroreProgetto
from .settings import cartella_dati
from .somiglianza import valutatore
from .workflows import analizza, per_invio, workflow_test_lora

rotte_kohya = APIRouter(prefix="/api/kohya")
rotte = APIRouter(prefix="/api/progetti/{pid}/personaggi/{cid}/addestramento")
_info_kohya: dict | None = None


def _app(req: Request):
    return req.app.state.app


def _arch(req: Request) -> ad.ArchivioAddestramento:
    return ad.ArchivioAddestramento(_app(req).progetti)


def _did(req: Request) -> ArchivioDidascalie:
    return ArchivioDidascalie(ArchivioDataset(_app(req).progetti))


# ---------------------------------------------------------------- processi

async def esegui_processo(cmd: list[str], cwd: Path | None, l: Lavoro, riga, coda: deque) -> int:
    """Esegue un comando leggendo l'uscita riga per riga (anche le righe di tqdm che finiscono con \\r)."""
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    try:
        proc = await asyncio.create_subprocess_exec(*cmd, cwd=str(cwd) if cwd else None, env=env,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    except FileNotFoundError:
        raise ErroreProgetto(f"Programma non trovato: {cmd[0]}") from None
    except NotImplementedError:
        # su Windows con un event loop "selector" asyncio non gestisce i processi: si usa un thread
        return await _esegui_in_thread(cmd, cwd, env, riga, coda)
    resto = b""
    try:
        while True:
            pezzo = await proc.stdout.read(8192)
            if not pezzo:
                break
            resto += pezzo
            parti = re.split(rb"[\r\n]", resto)
            resto = parti.pop()
            for p in parti:
                testo = p.decode("utf-8", "replace").rstrip()
                if testo.strip():
                    coda.append(testo)
                    riga(testo)
        if resto.strip():
            testo = resto.decode("utf-8", "replace").rstrip()
            coda.append(testo)
            riga(testo)
        return await proc.wait()
    except asyncio.CancelledError:
        await asyncio.shield(asyncio.to_thread(_termina, proc.pid))
        raise


async def _esegui_in_thread(cmd, cwd, env, riga, coda: deque) -> int:
    import subprocess
    loop = asyncio.get_running_loop()
    proc = subprocess.Popen(cmd, cwd=str(cwd) if cwd else None, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)

    def leggi():
        resto = b""
        while True:
            pezzo = proc.stdout.read1(8192) if hasattr(proc.stdout, "read1") else proc.stdout.read(8192)
            if not pezzo:
                break
            resto += pezzo
            parti = re.split(rb"[\r\n]", resto)
            resto = parti.pop()
            for p in parti:
                testo = p.decode("utf-8", "replace").rstrip()
                if testo.strip():
                    coda.append(testo)
                    loop.call_soon_threadsafe(riga, testo)
        if resto.strip():
            testo = resto.decode("utf-8", "replace").rstrip()
            coda.append(testo)
            loop.call_soon_threadsafe(riga, testo)
        return proc.wait()

    try:
        return await asyncio.to_thread(leggi)
    except asyncio.CancelledError:
        await asyncio.shield(asyncio.to_thread(_termina, proc.pid))
        raise


def _termina(pid: int, attesa: float = 20):
    """Chiude il processo e i suoi figli e aspetta che siano usciti: solo allora la VRAM è davvero libera."""
    try:
        p = psutil.Process(pid)
        tutti = [*p.children(recursive=True), p]
    except psutil.Error:
        return
    for x in tutti:
        try:
            x.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(tutti, timeout=attesa)


# ---------------------------------------------------------------- kohya

def _stato_kohya(ricontrolla: bool = False) -> dict:
    global _info_kohya
    k = ad.trova_kohya(cartella_dati())
    if not k:
        _info_kohya = None
        return {"installato": False, "cartella": str(ad.cartella_kohya(cartella_dati())), "piattaforma": ad.tipo_gpu()}
    if ricontrolla or _info_kohya is None or _info_kohya.get("cartella") != str(k.cartella):
        _info_kohya = ad.verifica_kohya(k)
    return {"installato": True, "piattaforma": ad.tipo_gpu(), **_info_kohya}


@rotte_kohya.get("")
async def kohya(ricontrolla: bool = False):
    return await asyncio.to_thread(_stato_kohya, ricontrolla)


class Installa(BaseModel):
    reinstalla: bool = False


@rotte_kohya.post("/installa")
async def installa(dati: Installa, req: Request):
    app = _app(req)
    if any(l.tipo == "kohya_installa" for l in app.gestore.attivi()):
        raise HTTPException(409, "L'installazione è già in corso.")

    async def lavoro(l: Lavoro):
        global _info_kohya
        cartella = ad.cartella_kohya(cartella_dati())
        python = await asyncio.to_thread(ad.python_per_kohya)
        if not python:
            raise ErroreProgetto("Serve Python 3.10, 3.11 o 3.12 per kohya (consigliato il 3.10). Installalo da "
                                 "https://www.python.org/downloads/ e riprova.")
        l.log(f"Python per kohya: {' '.join(python)}")
        if dati.reinstalla and (cartella / "venv").exists():
            l.log("Rimuovo il vecchio ambiente Python di kohya")
            await asyncio.to_thread(shutil.rmtree, cartella / "venv", True)
        git = shutil.which("git") is not None
        cartella.parent.mkdir(parents=True, exist_ok=True)
        if not git and not (cartella / "sdxl_train_network.py").exists():
            l.log("Git non trovato: scarico kohya come archivio zip")
            await asyncio.to_thread(_scarica_zip_kohya, cartella)
        gpu = ad.tipo_gpu()
        if gpu == "cpu":
            l.log("Nessuna GPU NVIDIA trovata: installo PyTorch per CPU (l'addestramento sarà lentissimo).", "avviso")
        passi = ad.comandi_installazione(cartella, python, gpu, git)
        if git and (cartella / "sdxl_train_network.py").exists() and not (cartella / ".git").exists():
            passi = [p for p in passi if p[1][0] != "git"]
        coda: deque = deque(maxlen=60)
        for i, (descrizione, cmd, cwd) in enumerate(passi):
            l.controlla()
            l.avanza(i / len(passi), descrizione)
            l.log(descrizione + "...")
            codice = await esegui_processo(cmd, cwd, l, lambda t: l.log(t, "debug"), coda)
            if codice != 0:
                dettaglio = "\n".join(list(coda)[-12:])
                raise ErroreProgetto(f"{descrizione}: non riuscito (codice {codice}).\n{dettaglio}")
        l.avanza(0.97, "verifico l'installazione")
        _info_kohya = None
        info = await asyncio.to_thread(_stato_kohya, True)
        if info.get("errore"):
            raise ErroreProgetto(f"kohya è installato ma PyTorch non parte: {info['errore']}")
        l.log(f"kohya pronto: PyTorch {info.get('torch')}, GPU {info.get('gpu') or 'non vista'}",
              "ok" if info.get("cuda") or info.get("mps") else "avviso")
        app.bus.pubblica({"tipo": "kohya", "dati": info})
        return info

    titolo = "Reinstallazione di kohya sd-scripts" if dati.reinstalla else "Installazione di kohya sd-scripts"
    return app.gestore.avvia("kohya_installa", titolo, lavoro).dict()


def _scarica_zip_kohya(cartella: Path):
    with tempfile.TemporaryDirectory() as tmp:
        z = Path(tmp) / "kohya.zip"
        with httpx.stream("GET", ad.ZIP_KOHYA, follow_redirects=True, timeout=120) as r:
            r.raise_for_status()
            with open(z, "wb") as f:
                for b in r.iter_bytes(1 << 20):
                    f.write(b)
        with zipfile.ZipFile(z) as zz:
            zz.extractall(tmp)
        interna = next(p for p in Path(tmp).iterdir() if p.is_dir())
        if cartella.exists():
            shutil.rmtree(cartella)
        shutil.move(str(interna), str(cartella))


# ---------------------------------------------------------------- stato e parametri

def _riassunto(req: Request, pid: str, cid: str) -> dict:
    app = _app(req)
    a = _arch(req)
    _, pers = ArchivioDataset(app.progetti).personaggio(pid, cid)
    c = a.config(pid, cid)
    immagini = len(_did(req).immagini(pid, cid)[0])
    stato = a.stato(pid, cid)
    uscita = a.cartella(pid, cid) / "uscita"
    suggerito = None
    try:
        ds = ArchivioDataset(app.progetti)
        conf = ds.config(pid, cid)
        if conf.workflow:
            suggerito = analizza(ds.leggi_workflow(pid, conf.workflow).workflow).checkpoint
    except ErroreProgetto:
        pass
    return {"config": c.model_dump(), "stato": stato.model_dump(), "epoche": ad.file_epoche(uscita, pers.trigger),
            "loss": a.loss(pid, cid), "immagini": immagini,
            "ripetizioni": ad.ripetizioni(c, immagini) if immagini else None,
            "passi_totali": ad.passi_totali(c, immagini) if immagini else 0,
            "preset_consigliato": ad.preset_per_vram(app.comfy.vram_totale),
            "checkpoint_suggerito": suggerito, "trigger": pers.trigger}


@rotte.get("")
async def riassunto(pid: str, cid: str, req: Request):
    return await asyncio.to_thread(_riassunto, req, pid, cid)


@rotte.put("/config")
async def salva_config(pid: str, cid: str, c: ad.ConfigAddestramento, req: Request):
    _arch(req).salva_config(pid, cid, c)
    return await asyncio.to_thread(_riassunto, req, pid, cid)


class SceltaPreset(BaseModel):
    preset: ad.Preset


@rotte.post("/preset")
async def applica_preset(pid: str, cid: str, dati: SceltaPreset, req: Request):
    a = _arch(req)
    a.salva_config(pid, cid, ad.preset(dati.preset, a.config(pid, cid)))
    return await asyncio.to_thread(_riassunto, req, pid, cid)


class PromptTest(BaseModel):
    prompt: list[str] = Field(min_length=1, max_length=8)


@rotte.put("/prompt-test")
async def prompt_test(pid: str, cid: str, dati: PromptTest, req: Request):
    a = _arch(req)
    s = a.stato(pid, cid)
    s.prompt_test = [p.strip() for p in dati.prompt if p.strip()] or s.prompt_test
    a.salva_stato(pid, cid, s)
    return s.model_dump()


# ---------------------------------------------------------------- addestramento

@rotte.post("/avvia")
async def avvia(pid: str, cid: str, req: Request):
    app = _app(req)
    a = _arch(req)
    did = _did(req)
    _, pers = did.dataset.personaggio(pid, cid)
    c = a.config(pid, cid)
    k = ad.trova_kohya(cartella_dati())
    if not k:
        raise HTTPException(409, "kohya sd-scripts non è installato: installalo dalla sezione «Trainer».")
    checkpoint = ad.risolvi_checkpoint(app.comfy.cartella or app.impostazioni.valori.comfy_dir, c.checkpoint)
    immagini = len(did.immagini(pid, cid)[0])
    if immagini < 5:
        raise HTTPException(400, f"Servono almeno 5 immagini nel dataset (ora {immagini}): completa gli Step 1 e 2.")

    async def lavoro(l: Lavoro):
        cartella = a.cartella(pid, cid)
        dataset = cartella / "dataset"
        uscita = cartella / "uscita"
        n = await asyncio.to_thread(did.esporta, pid, cid, dataset)
        l.log(f"Dataset pronto: {n} immagini con le loro didascalie")
        if uscita.exists() and any(uscita.iterdir()):
            cestino = app.progetti.radice / ".cestino" / f"{pid}-{cid}-lora-{int(time.time())}"
            cestino.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(uscita), str(cestino))
            l.log("Le epoche dell'addestramento precedente sono state spostate nel cestino")
        uscita.mkdir(parents=True, exist_ok=True)
        toml = cartella / "dataset.toml"
        toml.write_text(ad.toml_dataset(dataset, c, n), encoding="utf-8")
        cmd = ad.argomenti(k, c, checkpoint, toml, uscita, pers.trigger)
        (cartella / "comando.txt").write_text(" ".join(f'"{x}"' if " " in x else x for x in cmd), encoding="utf-8")
        totale = ad.passi_totali(c, n)
        l.log(f"{n} immagini × {ad.ripetizioni(c, n)} ripetizioni × {c.epoche} epoche ≈ {totale} passi "
              f"(preset {c.preset}, rank {c.rank}, {c.ottimizzatore})")
        if app.comfy.connesso:
            try:
                async with app.client() as client:
                    await client.libera_memoria()
                l.log("Ho liberato la memoria della GPU occupata da ComfyUI")
            except ComfyErrore:
                pass

        stato = a.stato(pid, cid)
        stato.ultimo_avvio, stato.ultimo_esito, stato.test = time.time(), "in corso", {}
        a.salva_stato(pid, cid, stato)
        av = ad.Avanzamento(totale=totale, epoche=c.epoche)
        punti: list[list[float]] = []
        ultimo_punto = [-1]
        ultimo_salvataggio = [time.time()]
        coda: deque = deque(maxlen=200)
        inizio = time.time()

        def riga(t: str):
            vecchio_salvato = av.salvato
            if ad.leggi_riga(t, av):
                passo_minimo = max(1, (av.totale or totale) // 400)
                if av.loss is not None and av.passo - ultimo_punto[0] >= passo_minimo:
                    punti.append([av.passo, round(av.loss, 5)])
                    ultimo_punto[0] = av.passo
                    app.bus.pubblica({"tipo": "addestramento", "progetto": pid, "personaggio": cid,
                                      "punto": punti[-1], "passo": av.passo, "totale": av.totale or totale,
                                      "epoca": av.epoca, "epoche": av.epoche, "velocita": av.velocita,
                                      "rimanente": av.rimanente})
                    if time.time() - ultimo_salvataggio[0] > 10:
                        a.salva_loss(pid, cid, punti)
                        ultimo_salvataggio[0] = time.time()
                if av.totale:
                    testo = f"passo {av.passo}/{av.totale}"
                    if av.epoca:
                        testo += f" · epoca {av.epoca}/{av.epoche}"
                    if av.rimanente:
                        testo += f" · mancano {av.rimanente}"
                    if av.loss is not None:
                        testo += f" · loss {av.loss:.4f}"
                    l.avanza(av.passo / av.totale, testo)
                if av.salvato and av.salvato != vecchio_salvato:
                    l.log(f"Salvata l'epoca: {Path(av.salvato).name}", "ok")
                    app.bus.pubblica({"tipo": "addestramento", "progetto": pid, "personaggio": cid, "epoche_cambiate": True})
                if "steps:" in t:
                    return
            livello = "avviso" if re.search(r"warn|warning", t, re.I) else "debug"
            if re.search(r"error|traceback|exception", t, re.I):
                livello = "errore"
            elif re.search(r"epoch \d+/\d+|caching|running training|num train images|num epochs", t, re.I):
                livello = "info"
            l.log(t, livello)

        l.avanza(0.0, "avvio di kohya (la prima volta prepara la cache: qualche minuto)")
        try:
            codice = await esegui_processo(cmd, k.cartella, l, riga, coda)
        finally:
            a.salva_loss(pid, cid, punti)
            stato = a.stato(pid, cid)
            stato.ultima_durata = time.time() - inizio
            a.salva_stato(pid, cid, stato)
        stato = a.stato(pid, cid)
        epoche = ad.file_epoche(uscita, pers.trigger)
        if codice != 0 or not epoche:
            stato.ultimo_esito = "errore"
            a.salva_stato(pid, cid, stato)
            testo = "\n".join(coda)
            spiegazione = ad.spiega_errore(testo) or "Guarda i dettagli nella console (filtro «Dettagli»)."
            raise ErroreProgetto(f"L'addestramento si è fermato (codice {codice}). {spiegazione}")
        stato.ultimo_esito = "completato"
        a.salva_stato(pid, cid, stato)
        l.log(f"Addestramento di {pers.nome} completato in {ad.durata(time.time() - inizio)}: {len(epoche)} epoche "
              "salvate. Ora prova le epoche per scegliere la migliore.", "ok")
        app.bus.pubblica({"tipo": "addestramento", "progetto": pid, "personaggio": cid, "epoche_cambiate": True})
        return {"epoche": len(epoche)}

    return app.gestore.avvia("addestramento", f"Addestramento del LoRA di {pers.nome}", lavoro,
                             progetto=pid, esclusivo=True).dict()


# ---------------------------------------------------------------- test delle epoche

class Prova(BaseModel):
    epoche: list[int] | None = None


async def _nome_lora(client, file: str) -> str:
    """Il nome con cui ComfyUI vede un file dentro models/loras (le sottocartelle cambiano tra sistemi)."""
    for nome in await client.modelli("loras"):
        if nome.replace("\\", "/").split("/")[-1] == file:
            return nome
    return f"comic_studio/{file}"


PAROLE_ITALIANE = re.compile(r"\b(con|una|uno|il|lo|la|gli|le|di|che|nel|nella|sul|sulla|per|mentre|dei|delle|"
                             r"è|sono|seduta|seduto|in piedi|capelli|occhi)\b", re.I)


def non_inglese(p: str) -> bool:
    return len(PAROLE_ITALIANE.findall(p)) >= 2


def prompt_di_prova(p: str, pers) -> str:
    """Il prompt di prova con la trigger word e il genere davanti, se mancano: senza trigger il LoRA non si accende."""
    testa = []
    if "{trigger}" not in p and pers.trigger not in p:
        testa.append("{trigger}")
    if "{genere}" not in p and pers.genere not in p:
        testa.append("{genere}")
    return ", ".join(testa + [p]) if testa else p


@rotte.post("/prova")
async def prova(pid: str, cid: str, dati: Prova, req: Request):
    app = _app(req)
    a = _arch(req)
    ds = ArchivioDataset(app.progetti)
    _, pers = ds.personaggio(pid, cid)
    c = a.config(pid, cid)
    uscita = a.cartella(pid, cid) / "uscita"
    tutte = ad.file_epoche(uscita, pers.trigger)
    if not tutte:
        raise HTTPException(400, "Non ci sono epoche da provare: addestra prima il LoRA.")
    if not app.comfy.connesso:
        raise HTTPException(409, "ComfyUI non è connesso: serve per provare le epoche.")
    numeri = dati.epoche or ad.epoche_da_provare([e["epoca"] for e in tutte])
    scelte = [e for e in tutte if e["epoca"] in numeri]
    cartella_lora = ad.cartella_lora_comfy(app.comfy.cartella or app.impostazioni.valori.comfy_dir)
    checkpoint = c.checkpoint
    if not checkpoint:
        raise HTTPException(400, "Manca il checkpoint nei parametri.")
    conf_ds = ds.config(pid, cid)
    qualita = tag_qualita(checkpoint, conf_ds)
    negativo = componi(conf_ds.prompt_negativo, {"negativo_qualita": qualita[1]})

    async def lavoro(l: Lavoro):
        stato = a.stato(pid, cid)
        prompt = [componi(f"{qualita[0]}, {prompt_di_prova(p, pers)}",
                          {"trigger": pers.trigger, "genere": pers.genere, "nome": pers.nome})
                  for p in stato.prompt_test]
        if any(non_inglese(p) for p in stato.prompt_test):
            l.log("Alcuni prompt di prova sembrano in italiano: il modello capisce solo l'inglese a tag (es. «"
                  "{trigger}, {genere}, solo, sitting, smile, upper body»). In italiano il risultato dice poco sul "
                  "LoRA.", "avviso")
        dest = a.cartella(pid, cid) / "test"
        dest.mkdir(parents=True, exist_ok=True)
        risultati: dict[str, dict] = {}
        totale = len(scelte) * len(prompt)
        fatte = 0
        async with app.client() as client:
            for e in scelte:
                copia = cartella_lora / f"test_{pers.trigger}-{e['epoca']:03d}.safetensors"
                await asyncio.to_thread(shutil.copy2, uscita / e["file"], copia)
                nome = await _nome_lora(client, copia.name)
                files = []
                for i, p in enumerate(prompt):
                    l.controlla()
                    wf, salva = workflow_test_lora(checkpoint, nome, p, negativo, 1000 + i)
                    def avanza(v, t, fatte=fatte):
                        l.avanza((fatte + v) / totale, f"epoca {e['epoca']} · prova {i + 1}/{len(prompt)} · {t}")
                    l.registra_workflow(wf)
                    uscite = await client.esegui(per_invio(wf), avanza, anteprima=l.imposta_anteprima)
                    img = (uscite.get(salva) or next(iter(uscite.values()), [None]))[0]
                    if not img:
                        raise ComfyErrore("ComfyUI non ha restituito l'immagine di prova.")
                    f = dest / f"epoca{e['epoca']:03d}_{i + 1}.png"
                    dati_img = await client.scarica(img)
                    f.write_bytes(dati_img)
                    l.imposta_anteprima(dati_img, "image/png", finale=True)
                    files.append(f.name)
                    fatte += 1
                risultati[str(e["epoca"])] = {"immagini": files, "punteggio": None}
                l.log(f"Provata l'epoca {e['epoca']}")
        try:
            rif = app.progetti.file_riferimento(pid, cid)
            val = await asyncio.to_thread(valutatore, cartella_dati() / "modelli", None, l.log)
            ordine = [k for k in risultati]
            percorsi = [rif] + [dest / f for k in ordine for f in risultati[k]["immagini"]]
            E = await asyncio.to_thread(val.vettori, percorsi)
            punti = E[1:] @ E[0]
            j = 0
            for k in ordine:
                n = len(risultati[k]["immagini"])
                risultati[k]["punteggio"] = round(float(np.mean(punti[j:j + n])), 4)
                j += n
        except ErroreProgetto:
            l.log("Nessuna immagine di riferimento: niente punteggio di somiglianza.", "avviso")
        stato = a.stato(pid, cid)
        stato.test = risultati
        a.salva_stato(pid, cid, stato)
        con_punti = {k: v["punteggio"] for k, v in risultati.items() if v["punteggio"] is not None}
        if con_punti:
            migliore = max(con_punti.values())
            consigliata = min((int(k) for k, v in con_punti.items() if v >= migliore - 0.01))
            l.log(f"Epoca consigliata: {consigliata} (la prima quasi somigliante quanto la migliore: le ultime "
                  "epoche tendono a copiare sempre le stesse pose)", "ok")
        app.bus.pubblica({"tipo": "addestramento", "progetto": pid, "personaggio": cid, "test": True})
        return risultati

    return app.gestore.avvia("addestramento_prova", f"Prova delle epoche di {pers.nome}", lavoro,
                             progetto=pid, esclusivo=True).dict()


@rotte.get("/test/{file}")
async def immagine_test(pid: str, cid: str, file: str, req: Request):
    if not re.fullmatch(r"epoca\d{3}_\d+\.png", file):
        raise HTTPException(404, "File non valido")
    f = _arch(req).cartella(pid, cid) / "test" / file
    if not f.exists():
        raise HTTPException(404, "Immagine non trovata")
    return FileResponse(f)


# ---------------------------------------------------------------- scelta del LoRA finale

class Scegli(BaseModel):
    epoca: int


@rotte.post("/scegli")
async def scegli(pid: str, cid: str, dati: Scegli, req: Request):
    app = _app(req)
    a = _arch(req)
    _, pers = ArchivioDataset(app.progetti).personaggio(pid, cid)
    uscita = a.cartella(pid, cid) / "uscita"
    e = next((x for x in ad.file_epoche(uscita, pers.trigger) if x["epoca"] == dati.epoca), None)
    if not e:
        raise HTTPException(404, f"L'epoca {dati.epoca} non esiste.")
    cartella_lora = ad.cartella_lora_comfy(app.comfy.cartella or app.impostazioni.valori.comfy_dir)
    dest = cartella_lora / f"{pers.trigger}.safetensors"
    await asyncio.to_thread(shutil.copy2, uscita / e["file"], dest)
    for prova_vecchia in cartella_lora.glob(f"test_{pers.trigger}-*.safetensors"):
        prova_vecchia.unlink(missing_ok=True)
    nome = f"comic_studio/{dest.name}"
    if app.comfy.connesso:
        try:
            async with app.client() as client:
                nome = await _nome_lora(client, dest.name)
        except ComfyErrore:
            pass
    s = a.stato(pid, cid)
    s.lora_finale, s.epoca_finale, s.origine = nome, dati.epoca, "addestrato"
    a.salva_stato(pid, cid, s)
    app.bus.log(f"LoRA di {pers.nome} pronto: epoca {dati.epoca} → {nome}", "ok")
    return s.model_dump()


class Esistente(BaseModel):
    lora: str | None


@rotte.post("/esistente")
async def esistente(pid: str, cid: str, dati: Esistente, req: Request):
    """Usa un LoRA già presente in ComfyUI (addestrato altrove) oppure toglie la scelta (None)."""
    a = _arch(req)
    s = a.stato(pid, cid)
    s.lora_finale = dati.lora
    s.epoca_finale = None
    s.origine = "esistente" if dati.lora else None
    a.salva_stato(pid, cid, s)
    return s.model_dump()
