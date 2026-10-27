"""Step 2 — Didascalie: tag automatici delle immagini tenute, trigger word, pulizia dei tratti fissi.

Ogni immagine del dataset riceve una didascalia (il futuro file .txt per kohya):
    <trigger>, <genere>, [tag sempre presenti], <tag dell'immagine senza i tratti fissi>

I tratti fissi (capelli, divisa, baffi…) si tolgono perché il LoRA li deve legare alla trigger word:
così basterà scrivere la trigger word per avere il personaggio completo.

I tag vengono da due fonti, anche insieme:
  - il tagger WD14 (ONNX), che guarda l'immagine vera
  - il prompt con cui l'immagine è stata generata (variante), sempre disponibile

File: <progetto>/personaggi/<pid>/didascalie/{config.json, tag.json, manuali.json}
"""
from __future__ import annotations

import csv
import io
import json
import re
import threading
import zipfile
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import numpy as np
from PIL import Image
from pydantic import BaseModel, Field

from .dataset import ArchivioDataset, InfoImmagine
from .projects import ErroreProgetto, Personaggio
from .somiglianza import scarica

REPO_TAGGER = {
    "wd-vit-tagger-v3": "SmilingWolf/wd-vit-tagger-v3",
    "wd-swinv2-tagger-v3": "SmilingWolf/wd-swinv2-tagger-v3",
    "wd-eva02-large-tagger-v3": "SmilingWolf/wd-eva02-large-tagger-v3",
}
SOGLIA_MINIMA = 0.2          # i tag sotto questa probabilità non vengono neanche salvati
EMOTICON = {"0_0", "(o)_(o)", "+_+", "+_-", "._.", "<o>_<o>", "<|>_<|>", "=_=", ">_<", "3_3", "6_9", ">_o",
            "@_@", "^_^", "o_o", "u_u", "x_x", "|_|", "||_||"}
GENERI = {"1girl", "1boy", "1other", "solo", "2girls", "2boys", "multiple girls", "multiple boys"}
# parole che indicano un tratto dell'aspetto: candidati a essere "fissi"
ASPETTO = re.compile(r"hair|eyes|eyebrows|skin|beard|mustache|moustache|stubble|freckles|mole|scar|breasts|"
                     r"uniform|hat|cap|headwear|glasses|eyewear|earrings|necktie|tie\b|shirt|jacket|coat|"
                     r"dress|skirt|pants|boots|gloves|belt|badge|tattoo|old man|old woman|fat|muscular|tall|"
                     r"bald|ponytail|bangs|braid|twintails|pointy ears")

Modalita = Literal["tagger", "prompt", "entrambi"]
_lock = threading.RLock()


class ConfigDidascalie(BaseModel):
    modalita: Modalita = "entrambi"
    modello: str = "wd-vit-tagger-v3"
    soglia: float = Field(default=0.35, ge=0.05, le=0.95)
    togli_tratti_fissi: bool = True          # toglie i tag che compaiono nella descrizione del personaggio
    # toglie anche i tratti dell'aspetto che ricorrono in quasi tutte le immagini (capelli, occhi, divisa…): così li
    # impara la trigger word. Se restano nelle didascalie il LoRA li lega a quei tag e la trigger da sola non li porta
    togli_ricorrenti: bool = True
    rimossi: list[str] = Field(default_factory=list)
    aggiunti: list[str] = Field(default_factory=list)     # sempre presenti, dopo trigger e genere
    sostituzioni: dict[str, str] = Field(default_factory=dict)
    massimo_tag: int = Field(default=40, ge=5, le=150)
    tag_stile: str = ""                      # es. "western comics (style)", messo in fondo


def normalizza_tag(t: str) -> str:
    t = t.strip().lower()
    if t not in EMOTICON:
        t = t.replace("_", " ")
    return re.sub(r"\s+", " ", t)


def separa(testo: str) -> list[str]:
    return [normalizza_tag(x) for x in testo.split(",") if x.strip()]


# ---------------------------------------------------------------- tagger WD14

class Tagger:
    def __init__(self, modello: Path, etichette: Path):
        import onnxruntime as ort
        opzioni = ort.SessionOptions()
        opzioni.log_severity_level = 3
        self.sessione = ort.InferenceSession(str(modello), opzioni, providers=["CPUExecutionProvider"])
        ingresso = self.sessione.get_inputs()[0]
        self.ingresso = ingresso.name
        lato = ingresso.shape[1] if len(ingresso.shape) == 4 else None
        self.lato = lato if isinstance(lato, int) else 448
        self.uscita = self.sessione.get_outputs()[0].name
        self.nomi: list[str] = []
        self.categorie: list[int] = []
        with open(etichette, newline="", encoding="utf-8") as f:
            for riga in csv.DictReader(f):
                self.nomi.append(normalizza_tag(riga["name"]))
                self.categorie.append(int(riga["category"]))
        self.categorie_np = np.array(self.categorie)

    def prepara(self, img: Image.Image) -> np.ndarray:
        img = img.convert("RGBA")
        fondo = Image.new("RGBA", img.size, (255, 255, 255, 255))
        fondo.alpha_composite(img)
        img = fondo.convert("RGB")
        lato = max(img.size)
        quadrato = Image.new("RGB", (lato, lato), (255, 255, 255))
        quadrato.paste(img, ((lato - img.width) // 2, (lato - img.height) // 2))
        if lato != self.lato:
            quadrato = quadrato.resize((self.lato, self.lato), Image.BICUBIC)
        a = np.asarray(quadrato, dtype=np.float32)[:, :, ::-1]      # RGB -> BGR
        return np.ascontiguousarray(a)

    def tagga(self, immagini: list[Path], avanzamento: Callable[[float, str], None] | None = None,
              annullato: Callable[[], bool] | None = None) -> dict[str, dict[str, float]]:
        out = {}
        for i, p in enumerate(immagini):
            if annullato and annullato():
                break
            with Image.open(p) as img:
                x = self.prepara(img)[None]
            prob = self.sessione.run([self.uscita], {self.ingresso: x})[0][0]
            # categoria 0 = generali, 4 = personaggi noti; 9 = rating (ignorati)
            tag = {self.nomi[j]: round(float(prob[j]), 4) for j in np.where(prob >= SOGLIA_MINIMA)[0]
                   if self.categorie[j] in (0, 4)}
            out[p.name] = tag
            if avanzamento:
                avanzamento((i + 1) / len(immagini), f"{i + 1}/{len(immagini)} immagini")
        return out


_tagger: dict[str, Tagger] = {}


def carica_tagger(cartella_modelli: Path, nome: str, avanzamento=None, log=None) -> Tagger:
    with _lock:
        if nome in _tagger:
            return _tagger[nome]
        try:
            import onnxruntime  # noqa: F401
        except ImportError:
            raise ErroreProgetto("onnxruntime non è installato: riavvia il programma con avvia.bat / avvia.sh "
                                 "perché installi le librerie, oppure usa le didascalie dal prompt.") from None
        repo = REPO_TAGGER.get(nome)
        if not repo:
            raise ErroreProgetto(f"Tagger sconosciuto: {nome}")
        d = cartella_modelli / nome
        modello, etichette = d / "model.onnx", d / "selected_tags.csv"
        base = f"https://huggingface.co/{repo}/resolve/main"
        try:
            if not etichette.exists():
                scarica(f"{base}/selected_tags.csv", etichette)
            if not modello.exists():
                if log:
                    log(f"Scarico il tagger {nome} (circa 350-450 MB, una volta sola)...", "info")
                scarica(f"{base}/model.onnx", modello, avanzamento, timeout=120)
        except Exception as e:  # noqa: BLE001
            raise ErroreProgetto(f"Non riesco a scaricare il tagger {nome}: {e}. Sei offline? Puoi usare le "
                                 "didascalie «dal prompt», che non hanno bisogno del tagger.") from None
        _tagger[nome] = Tagger(modello, etichette)
        return _tagger[nome]


# ---------------------------------------------------------------- composizione

def tratti_fissi(p: Personaggio) -> set[str]:
    return set(separa(p.descrizione))


def e_tratto(t: str, tratti: set[str]) -> bool:
    """Il tag è uno dei tratti, anche detto con meno parole: «blonde hair» e «long hair» stanno in «long straight
    blonde hair», «blue eyes» in «piercing blue eyes»."""
    if t in tratti:
        return True
    parole = set(t.split())
    return len(parole) > 1 and any(parole <= set(x.split()) for x in tratti)


QUOTA_RICORRENTI = 0.7


def ricorrenti(conteggio: dict[str, int], n: int) -> set[str]:
    """Tratti dell'aspetto presenti in quasi tutte le immagini: fanno parte del personaggio."""
    return {t for t, k in conteggio.items() if t not in GENERI and k / max(1, n) >= QUOTA_RICORRENTI
            and ASPETTO.search(t)}


def candidati(info: InfoImmagine, grezzi: dict[str, float] | None, c: ConfigDidascalie) -> list[tuple[str, float]]:
    """Tag dell'immagine prima della pulizia, ordinati per importanza."""
    tag: dict[str, float] = {}
    if c.modalita in ("tagger", "entrambi") and grezzi:
        for t, p in grezzi.items():
            if p >= c.soglia:
                tag[t] = p
    if c.modalita in ("prompt", "entrambi") or (c.modalita == "tagger" and not grezzi):
        for i, t in enumerate(separa(info.variante)):
            tag.setdefault(t, 0.99 - i * 0.001)      # i tag del prompt sono "certi", nell'ordine scritto
    return sorted(tag.items(), key=lambda kv: -kv[1])


def rimossi_effettivi(p: Personaggio, c: ConfigDidascalie) -> set[str]:
    via = {normalizza_tag(t) for t in c.rimossi}
    if c.togli_tratti_fissi:
        via |= tratti_fissi(p)
    return via


def da_togliere(t: str, p: Personaggio, c: ConfigDidascalie, extra: set[str] | frozenset = frozenset()) -> bool:
    """Il tag va tolto dalle didascalie: tolto a mano, tratto del personaggio (anche detto con meno parole), aspetto
    del riferimento usato nel dataset, o tratto che ricorre in quasi tutte le immagini (`extra`)."""
    if t in rimossi_effettivi(p, c) or t in extra:
        return True
    return c.togli_tratti_fissi and e_tratto(t, tratti_fissi(p))


def componi(p: Personaggio, info: InfoImmagine, grezzi: dict[str, float] | None, c: ConfigDidascalie,
            extra: set[str] | frozenset = frozenset()) -> str:
    sost = {normalizza_tag(k): normalizza_tag(v) for k, v in c.sostituzioni.items() if k.strip()}
    testa = [p.trigger, p.genere]
    if p.genere != "1other":
        testa.append("solo")
    testa += [normalizza_tag(t) for t in c.aggiunti if t.strip()]
    stile = separa(c.tag_stile)
    visti = set(testa) | set(stile)
    corpo = []
    for t, _ in candidati(info, grezzi, c):
        t = sost.get(t, t)
        if not t or da_togliere(t, p, c, extra) or t in visti or t in GENERI:
            continue
        visti.add(t)
        corpo.append(t)
    corpo = corpo[:max(0, c.massimo_tag - len(testa) - len(stile))]
    return ", ".join(dict.fromkeys(testa + corpo + stile))


# ---------------------------------------------------------------- archivio

class ArchivioDidascalie:
    def __init__(self, dataset: ArchivioDataset):
        self.dataset = dataset

    def cartella(self, pid: str, cid: str) -> Path:
        return self.dataset.progetti.cartella_personaggio(pid, cid) / "didascalie"

    def _leggi(self, f: Path, predefinito):
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return predefinito

    def _scrivi(self, f: Path, dati):
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(dati, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(f)

    def config(self, pid: str, cid: str) -> ConfigDidascalie:
        d = self._leggi(self.cartella(pid, cid) / "config.json", None)
        try:
            return ConfigDidascalie(**d) if d else ConfigDidascalie()
        except ValueError:
            return ConfigDidascalie()

    def salva_config(self, pid: str, cid: str, c: ConfigDidascalie):
        self.dataset.personaggio(pid, cid)
        self._scrivi(self.cartella(pid, cid) / "config.json", c.model_dump())

    def tag(self, pid: str, cid: str) -> dict[str, dict[str, float]]:
        return self._leggi(self.cartella(pid, cid) / "tag.json", {})

    def salva_tag(self, pid: str, cid: str, nuovi: dict[str, dict[str, float]]):
        with _lock:
            t = self.tag(pid, cid)
            t.update(nuovi)
            self._scrivi(self.cartella(pid, cid) / "tag.json", t)

    def manuali(self, pid: str, cid: str) -> dict[str, str]:
        return self._leggi(self.cartella(pid, cid) / "manuali.json", {})

    def imposta_manuale(self, pid: str, cid: str, file: str, testo: str | None):
        with _lock:
            m = self.manuali(pid, cid)
            if testo is None:
                m.pop(file, None)
            else:
                m[file] = ", ".join(dict.fromkeys(x.strip() for x in testo.replace("\n", ",").split(",") if x.strip()))
            self._scrivi(self.cartella(pid, cid) / "manuali.json", m)

    def immagini(self, pid: str, cid: str) -> tuple[list[InfoImmagine], bool]:
        """Le immagini tenute nello Step 1 (se nessuna è stata scelta: tutte tranne le scartate)."""
        tutte = self.dataset.immagini(pid, cid)
        tenute = [i for i in tutte if i.stato == "tenuta"]
        if tenute:
            return tenute, True
        return [i for i in tutte if i.stato != "scartata"], False

    def _da_togliere_in_piu(self, pid: str, cid: str, pers, c: ConfigDidascalie, imm, tag) -> tuple[set[str], Counter]:
        """I tag tolti in automatico oltre ai tratti: l'aspetto del riferimento usato nel dataset e, se richiesto, i
        tratti dell'aspetto che ricorrono in quasi tutte le immagini. Restituisce anche il conteggio dei tag."""
        conteggio: Counter[str] = Counter()
        for i in imm:
            for t, _ in candidati(i, tag.get(i.file), c):
                conteggio[t] += 1
        extra: set[str] = set()
        if c.togli_tratti_fissi:
            try:
                extra |= set(separa(self.dataset.config(pid, cid).aspetto))
            except Exception:  # noqa: BLE001 - senza configurazione del dataset
                pass
        if c.togli_ricorrenti:
            extra |= ricorrenti(conteggio, len(imm))
        return extra - {normalizza_tag(t) for t in c.aggiunti}, conteggio

    def stato(self, pid: str, cid: str) -> dict:
        _, pers = self.dataset.personaggio(pid, cid)
        c = self.config(pid, cid)
        imm, da_selezione = self.immagini(pid, cid)
        tag, manuali = self.tag(pid, cid), self.manuali(pid, cid)
        extra, _ = self._da_togliere_in_piu(pid, cid, pers, c, imm, tag)
        conteggio: Counter[str] = Counter()
        prob_media: dict[str, list[float]] = {}
        righe = []
        for i in imm:
            for t, p in candidati(i, tag.get(i.file), c):
                conteggio[t] += 1
                prob_media.setdefault(t, []).append(p)
            auto = componi(pers, i, tag.get(i.file), c, extra)
            righe.append({"file": i.file, "numero": i.numero, "auto": auto, "testo": manuali.get(i.file, auto),
                          "manuale": i.file in manuali, "analizzata": i.file in tag, "creato": i.creato})
        n = max(1, len(imm))
        sost = {normalizza_tag(k): normalizza_tag(v) for k, v in c.sostituzioni.items()}
        frequenze = []
        for t, k in conteggio.most_common():
            if t in GENERI:
                continue
            rimosso = da_togliere(t, pers, c, extra)
            fisso = rimosso and t not in {normalizza_tag(x) for x in c.rimossi}
            suggerito = (not rimosso and k / n >= QUOTA_RICORRENTI and bool(ASPETTO.search(t)))
            frequenze.append({"tag": t, "conteggio": k, "quota": round(k / n, 3),
                              "probabilita": round(float(np.mean(prob_media[t])), 3), "rimosso": rimosso,
                              "fisso": fisso, "suggerito": suggerito, "sostituito": sost.get(t)})
        return {"config": c.model_dump(), "immagini": righe, "frequenze": frequenze, "totale": len(imm),
                "analizzate": sum(1 for i in imm if i.file in tag), "da_selezione": da_selezione,
                "trigger": pers.trigger}

    def didascalie_finali(self, pid: str, cid: str) -> list[tuple[InfoImmagine, str]]:
        _, pers = self.dataset.personaggio(pid, cid)
        c = self.config(pid, cid)
        imm, _ = self.immagini(pid, cid)
        tag, manuali = self.tag(pid, cid), self.manuali(pid, cid)
        extra, _ = self._da_togliere_in_piu(pid, cid, pers, c, imm, tag)
        return [(i, manuali.get(i.file) or componi(pers, i, tag.get(i.file), c, extra)) for i in imm]

    def esporta(self, pid: str, cid: str, dest: Path) -> int:
        """Scrive immagini e .txt in una cartella (quella che userà l'addestramento)."""
        finali = self.didascalie_finali(pid, cid)
        if not finali:
            raise ErroreProgetto("Il dataset è vuoto: torna allo Step 1.")
        dest.mkdir(parents=True, exist_ok=True)
        for vecchio in dest.iterdir():
            if vecchio.is_file():
                vecchio.unlink()
        sorgente = self.dataset.cartella(pid, cid) / "generate"
        for info, testo in finali:
            (dest / info.file).write_bytes((sorgente / info.file).read_bytes())
            (dest / info.file).with_suffix(".txt").write_text(testo + "\n", encoding="utf-8")
        return len(finali)

    def zip(self, pid: str, cid: str) -> bytes:
        finali = self.didascalie_finali(pid, cid)
        if not finali:
            raise ErroreProgetto("Il dataset è vuoto: torna allo Step 1.")
        sorgente = self.dataset.cartella(pid, cid) / "generate"
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w", zipfile.ZIP_STORED) as z:
            for info, testo in finali:
                z.write(sorgente / info.file, info.file)
                z.writestr(Path(info.file).with_suffix(".txt").name, testo + "\n")
        return b.getvalue()
