"""Somiglianza tra immagini con CLIP (ONNX, senza PyTorch).

Il modello visivo di CLIP ViT-B/32 quantizzato (circa 90 MB) viene scaricato la prima volta in
<cartella dati>/modelli/. Se onnxruntime o il download non sono disponibili si usa un metodo semplice
(istogramma dei colori + impronta della forma), molto meno preciso ma sempre disponibile.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

import httpx
import numpy as np
from PIL import Image

URL_MODELLI = [
    "https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main/onnx/vision_model_quantized.onnx",
    "https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main/onnx/vision_model.onnx",
]
MEDIA = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
DEVIAZIONE = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)

Avanzamento = Callable[[float, str], None]


def scarica(url: str, dest: Path, avanzamento: Avanzamento | None = None, timeout: float = 60) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".parziale")
    with httpx.stream("GET", url, follow_redirects=True, timeout=timeout) as r:
        r.raise_for_status()
        totale = int(r.headers.get("content-length") or 0)
        fatto = 0
        with open(tmp, "wb") as f:
            for blocco in r.iter_bytes(1 << 20):
                f.write(blocco)
                fatto += len(blocco)
                if avanzamento and totale:
                    avanzamento(fatto / totale, f"download {fatto / 1e6:.0f}/{totale / 1e6:.0f} MB")
    tmp.replace(dest)
    return dest


def prepara(img: Image.Image, lato: int = 224) -> np.ndarray:
    img = img.convert("RGB")
    w, h = img.size
    s = lato / min(w, h)
    img = img.resize((max(lato, round(w * s)), max(lato, round(h * s))), Image.BICUBIC)
    w, h = img.size
    x, y = (w - lato) // 2, (h - lato) // 2
    a = np.asarray(img.crop((x, y, x + lato, y + lato)), dtype=np.float32) / 255.0
    a = (a - MEDIA) / DEVIAZIONE
    return a.transpose(2, 0, 1)


def _normalizza(e: np.ndarray) -> np.ndarray:
    return e / np.maximum(np.linalg.norm(e, axis=-1, keepdims=True), 1e-8)


class Valutatore:
    """Calcola vettori normalizzati per un elenco di immagini."""

    nome = "base"

    def vettori(self, immagini: list[Path], avanzamento: Avanzamento | None = None) -> np.ndarray:
        raise NotImplementedError


class ValutatoreClip(Valutatore):
    nome = "CLIP ViT-B/32"

    def __init__(self, modello: Path):
        import onnxruntime as ort
        opzioni = ort.SessionOptions()
        opzioni.log_severity_level = 3
        self.sessione = ort.InferenceSession(str(modello), opzioni, providers=["CPUExecutionProvider"])
        self.ingresso = self.sessione.get_inputs()[0].name
        uscite = [o.name for o in self.sessione.get_outputs()]
        self.uscita = "image_embeds" if "image_embeds" in uscite else uscite[-1]

    def vettori(self, immagini, avanzamento=None):
        out = []
        for i in range(0, len(immagini), 8):
            lotto = np.stack([prepara(Image.open(p)) for p in immagini[i:i + 8]])
            e = self.sessione.run([self.uscita], {self.ingresso: lotto})[0]
            if e.ndim == 3:            # last_hidden_state: usa il token CLS
                e = e[:, 0, :]
            out.append(_normalizza(e.astype(np.float32)))
            if avanzamento:
                avanzamento(min(1.0, (i + 8) / len(immagini)), f"{min(i + 8, len(immagini))}/{len(immagini)} immagini")
        return np.concatenate(out) if out else np.zeros((0, 512), np.float32)


class ValutatoreSemplice(Valutatore):
    """Istogramma dei colori (HSV) + impronta della forma 16x16: grezzo ma senza dipendenze."""

    nome = "metodo semplice (colori e forma)"

    def vettori(self, immagini, avanzamento=None):
        out = []
        for i, p in enumerate(immagini):
            img = Image.open(p).convert("RGB")
            hsv = np.asarray(img.convert("HSV").resize((96, 96)), dtype=np.float32)
            ist, _ = np.histogramdd(hsv.reshape(-1, 3), bins=(12, 4, 4), range=((0, 256),) * 3)
            ist = ist.ravel() / ist.sum()
            forma = np.asarray(img.convert("L").resize((16, 16)), dtype=np.float32).ravel()
            forma = (forma - forma.mean()) / (forma.std() + 1e-6)
            out.append(np.concatenate([np.sqrt(ist) * 3.0, forma / 16.0]))
            if avanzamento:
                avanzamento((i + 1) / len(immagini), f"{i + 1}/{len(immagini)} immagini")
        return _normalizza(np.array(out, dtype=np.float32)) if out else np.zeros((0, 256), np.float32)


_cache: dict[str, Valutatore] = {}
_lock = threading.Lock()


def valutatore(cartella_modelli: Path, avanzamento: Avanzamento | None = None,
               log: Callable[[str, str], None] | None = None) -> Valutatore:
    """CLIP se possibile (scaricandolo la prima volta), altrimenti il metodo semplice."""
    with _lock:
        if "clip" in _cache:
            return _cache["clip"]
        try:
            import onnxruntime  # noqa: F401
        except ImportError:
            if log:
                log("onnxruntime non è installato: uso il metodo semplice per la somiglianza.", "avviso")
            return _cache.setdefault("semplice", ValutatoreSemplice())
        for url in URL_MODELLI:
            dest = cartella_modelli / Path(url).name
            try:
                if not dest.exists():
                    if log:
                        log(f"Scarico il modello CLIP per la somiglianza ({Path(url).name}, una volta sola)...", "info")
                    scarica(url, dest, avanzamento)
                _cache["clip"] = ValutatoreClip(dest)
                return _cache["clip"]
            except Exception as e:  # noqa: BLE001 - download o modello non valido: si prova il successivo
                if log:
                    log(f"Modello {Path(url).name} non disponibile: {e}", "avviso")
                dest.unlink(missing_ok=True)
        if log:
            log("CLIP non disponibile (sei offline?): uso il metodo semplice, meno preciso.", "avviso")
        return _cache.setdefault("semplice", ValutatoreSemplice())


def scegli(punteggi: list[float], vettori: np.ndarray, gruppi: list[str], quante: int,
           quote: dict[str, float] | None = None, soglia_doppioni: float = 0.96,
           esclusi: set[int] = frozenset(), forzati: set[int] = frozenset()) -> list[int]:
    """Indici delle immagini da tenere: le più somiglianti, distribuite tra i gruppi (inquadrature)
    secondo le quote, senza quasi-doppioni. `forzati` sono tenute in ogni caso, `esclusi` mai."""
    scelti: list[int] = list(forzati)

    def prova(i: int) -> bool:
        if i in scelti or i in esclusi:
            return False
        if any(float(vettori[i] @ vettori[j]) > soglia_doppioni for j in scelti):
            return False
        scelti.append(i)
        return True

    ordine = sorted(range(len(punteggi)), key=lambda i: -punteggi[i])
    if quote:
        totale_quote = sum(quote.values()) or 1
        for g, q in quote.items():
            n = round(quante * q / totale_quote) - sum(1 for i in scelti if gruppi[i] == g)
            for i in ordine:
                if n <= 0 or len(scelti) >= quante:
                    break
                if gruppi[i] == g and prova(i):
                    n -= 1
    for i in ordine:
        if len(scelti) >= quante:
            break
        prova(i)
    return scelti
