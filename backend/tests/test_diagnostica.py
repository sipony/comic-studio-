import json
import os
import shutil
import struct
import subprocess

import pytest

from app import diagnostica as dg
from app.modelinfo import GB, analizza, consiglio_spazio, famiglia_da_nome


def safetensors(f, dtype="F16", meta=None, extra=0):
    intest = {"model.weight": {"dtype": dtype, "shape": [2, 2], "data_offsets": [0, 8]}}
    if meta:
        intest["__metadata__"] = meta
    b = json.dumps(intest).encode()
    f.write_bytes(struct.pack("<Q", len(b)) + b + b"\0" * (8 + extra))
    return f


def test_famiglia_dal_nome():
    assert famiglia_da_nome("waiIllustriousSDXL_v170.safetensors") == "illustrious"
    assert famiglia_da_nome("ponyDiffusionV6XL.safetensors") == "pony"
    assert famiglia_da_nome("noobaiXLNAIXL_vPred10.safetensors") == "noobai"
    assert famiglia_da_nome("flux1-dev-Q4_K_S.gguf") == "flux"
    assert famiglia_da_nome("sd_xl_base_1.0.safetensors") == "sdxl"
    assert famiglia_da_nome("modello.safetensors") is None


def test_analizza_intestazione(tmp_path):
    i = analizza(safetensors(tmp_path / "x.safetensors", "BF16", {"modelspec.architecture": "stable-diffusion-xl-v1-base"}))
    assert i.precisione == "bf16" and i.famiglia == "sdxl" and not i.quantizzato
    i = analizza(safetensors(tmp_path / "pony_fp8.safetensors", "F8_E4M3"))
    assert i.precisione == "fp8" and i.quantizzato and i.famiglia == "pony"
    g = tmp_path / "flux1-dev-Q5_K_S.gguf"
    g.write_bytes(b"GGUF")
    i = analizza(g)
    assert i.quantizzato and i.precisione == "q5_k_s" and i.famiglia == "flux"
    rotto = tmp_path / "rotto.safetensors"
    rotto.write_bytes(b"\xff" * 20)
    assert analizza(rotto).precisione is None


def test_consiglio_fp32():
    from app.modelinfo import InfoModello
    assert "fp16" in consiglio_spazio(InfoModello("big.safetensors", int(13 * GB), "safetensors", "sdxl", "fp32"))
    assert consiglio_spazio(InfoModello("ok.safetensors", int(6.5 * GB), "safetensors", "sdxl", "fp16")) is None


@pytest.mark.asyncio
async def test_diagnostica_completa_senza_rete(cartella_comfy, tmp_path):
    (cartella_comfy / "custom_nodes" / "ComfyUI_IPAdapter_plus").mkdir(parents=True)
    (cartella_comfy / "custom_nodes" / "comfyui_controlnet_aux").mkdir()
    (cartella_comfy / "models" / "ipadapter").mkdir()
    (cartella_comfy / "models" / "ipadapter" / "ip-adapter-plus_sdxl_vit-h.safetensors").write_bytes(b"x")
    safetensors(cartella_comfy / "models" / "checkpoints" / "waiIllustriousSDXL.safetensors")
    dispositivi = [{"name": "cuda:0 NVIDIA GeForce RTX 4070 Laptop GPU : cudaMallocAsync", "type": "cuda",
                    "vram_total": 8 * GB, "vram_free": 7 * GB}]
    nodi = {"IPAdapterAdvanced", "KSampler"}       # controlnet_aux presente su disco ma non caricato
    r = await dg.diagnostica(str(cartella_comfy), str(cartella_comfy), "0.3.40", dispositivi, nodi,
                             tmp_path / "dati", tmp_path, rete=False)
    d = r.dict()
    voci = {v["nome"]: v for v in d["voci"]}
    assert d["hardware"]["gpu"][0]["nome"] == "NVIDIA GeForce RTX 4070 Laptop GPU"
    assert voci["Scheda video"]["esito"] == "ok"
    assert voci["ComfyUI_IPAdapter_plus"]["esito"] == "ok"
    assert voci["comfyui_controlnet_aux"]["esito"] == "errore" and "non caricato" in voci["comfyui_controlnet_aux"]["dettaglio"]
    assert voci["CLIP Vision ViT-H (per IPAdapter)"]["esito"] == "errore"
    assert voci["IPAdapter per SDXL"]["esito"] == "ok"
    assert any("fp8" in c for c in d["consigli"]) and any("portatile" in c for c in d["consigli"])
    assert any(m["famiglia"] == "illustrious" for m in d["modelli"])
    assert not d["aggiornamenti_controllati"]


def git(cwd, *a):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, env=env)


@pytest.mark.asyncio
@pytest.mark.skipif(shutil.which("git") is None, reason="git non installato")
async def test_aggiornamenti_git(tmp_path):
    remoto = tmp_path / "remoto"
    remoto.mkdir()
    git(remoto, "init", "-q", "-b", "main")
    (remoto / "a").write_text("1")
    git(remoto, "add", ".")
    git(remoto, "commit", "-qm", "uno")
    copia = tmp_path / "copia"
    git(tmp_path, "clone", "-q", str(remoto), str(copia))
    assert (await dg.git_aggiornamento(copia))[1] == "ok"
    (remoto / "a").write_text("2")
    git(remoto, "commit", "-qam", "due")
    nome, esito, testo = await dg.git_aggiornamento(copia)
    assert esito == "avviso" and "disponibile" in testo
    assert await dg.git_aggiornamento(tmp_path / "niente") is None


@pytest.mark.asyncio
async def test_aggiornamenti_release_e_librerie(cartella_comfy, tmp_path, monkeypatch):
    async def ultima():
        return "0.4.0"

    async def obsolete():
        return [{"name": "fastapi", "version": "0.115.0", "latest_version": "0.120.0"}]

    monkeypatch.setattr(dg, "ultima_release_comfy", ultima)
    monkeypatch.setattr(dg, "librerie_obsolete", obsolete)
    r = dg.Rapporto()
    await dg.controlla_aggiornamenti(r, cartella_comfy, None, "0.3.40", tmp_path)
    voci = {v.nome: v for v in r.voci}
    assert voci["ComfyUI (release)"].esito == "avviso" and "0.4.0" in voci["ComfyUI (release)"].dettaglio
    assert "fastapi" in voci["Librerie di Comic Studio"].dettaglio


def test_confronta_versioni():
    assert dg.confronta_versioni("0.3.40", "0.4.0") < 0
    assert dg.confronta_versioni("v0.10.1", "0.9.9") > 0
    assert dg.confronta_versioni("1.2.3", "1.2.3") == 0
