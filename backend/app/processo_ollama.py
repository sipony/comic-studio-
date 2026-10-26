"""Il processo di Ollama sul computer: quali «ollama serve» sono in esecuzione, come fermarli, cosa dice il registro.

Comic Studio avvia Ollama come processo separato (vedi `ServizioIA`), con l'uscita in
<cartella dati>/strumenti/ollama/ollama.log. Un Ollama aperto in un altro modo (servizio di sistema su Linux,
app di Ollama su Windows e macOS, terminale) si usa lo stesso; fermarlo si può solo se è dello stesso utente.
"""
from __future__ import annotations

import os
import platform
import re
from dataclasses import dataclass


@dataclass
class ProcessoOllama:
    pid: int
    utente: str | None
    porta: int | None          # porta su cui ascolta, se si riesce a leggerla
    mio: bool                  # dello stesso utente di Comic Studio (quindi si può fermare)


def _utente_corrente() -> str | None:
    try:
        import getpass
        return getpass.getuser()
    except Exception:  # noqa: BLE001
        return None


def _e_ollama_serve(cmdline: list[str]) -> bool:
    """`ollama serve`, anche se lanciato attraverso un interprete (`python …/ollama serve`)."""
    for i, a in enumerate(cmdline[:-1]):
        if os.path.basename(a).lower() in ("ollama", "ollama.exe") and cmdline[i + 1] == "serve":
            return True
    return False


def processi(porta: int | None = None) -> list[ProcessoOllama]:
    """I processi `ollama serve` in esecuzione; con `porta`, si escludono quelli che ascoltano su un'altra."""
    import psutil
    io = _utente_corrente()
    trovati = []
    for p in psutil.process_iter(["pid", "cmdline", "username"]):
        try:
            cmd = p.info.get("cmdline") or []
            if not _e_ollama_serve(cmd):
                continue
            utente = p.info.get("username")
            if utente and "\\" in utente:               # Windows: DOMINIO\nome
                utente = utente.split("\\")[-1]
            ascolta = None
            try:
                ascolta = next((c.laddr.port for c in p.net_connections(kind="tcp")
                                if c.status == psutil.CONN_LISTEN), None)
            except (psutil.Error, OSError):
                pass
            if porta and ascolta and ascolta != porta:
                continue
            trovati.append(ProcessoOllama(p.pid, utente, ascolta, mio=not utente or not io or utente == io))
        except (psutil.Error, OSError):
            continue
    return trovati


def termina(lista: list[ProcessoOllama], attesa: float = 10) -> tuple[list[int], list[ProcessoOllama]]:
    """Ferma i processi (con i figli, cioè i modelli caricati); restituisce i fermati e quelli senza permesso."""
    import psutil
    fermati, negati, da_attendere = [], [], []
    for x in lista:
        try:
            p = psutil.Process(x.pid)
            figli = p.children(recursive=True)
            p.terminate()
            for f in figli:
                try:
                    f.terminate()
                except psutil.Error:
                    pass
            da_attendere += [p, *figli]
            fermati.append(x.pid)
        except psutil.AccessDenied:
            negati.append(x)
        except psutil.NoSuchProcess:
            pass
    _, vivi = psutil.wait_procs(da_attendere, timeout=attesa)
    for v in vivi:
        try:
            v.kill()
        except psutil.Error:
            pass
    return fermati, negati


def come_fermarlo(negati: list[ProcessoOllama]) -> str:
    """Cosa fare quando Ollama è di un altro utente (di solito il servizio di sistema)."""
    chi = negati[0].utente if negati else None
    sistema = platform.system()
    if sistema == "Linux":
        return (f"Ollama è avviato dal servizio di sistema{f' (utente «{chi}»)' if chi else ''}: Comic Studio non ha i "
                "permessi per fermarlo. Da un terminale: «sudo systemctl restart ollama» per riavviarlo, «sudo "
                "systemctl stop ollama» per fermarlo (e «sudo systemctl disable ollama» se vuoi che lo gestisca "
                "Comic Studio).")
    if sistema == "Darwin":
        return "Ollama è aperto da un altro utente: chiudilo dall'icona di Ollama nella barra dei menu."
    return "Ollama è aperto da un altro utente o dal sistema: chiudilo dall'icona di Ollama vicino all'orologio."


# avvisi di Ollama che non riguardano Comic Studio (servizi online di ollama.com, senza rete)
AVVISI_INNOCUI = ("model recommendations refresh failed", "cloud cache hydration failed")


def livello_riga(riga: str) -> str | None:
    """Livello di log di una riga scritta da Ollama; None per le righe da non mostrare (le richieste HTTP)."""
    if riga.startswith("[GIN"):
        return None
    r = riga.lower()
    if any(x in r for x in AVVISI_INNOCUI):
        return "debug"
    if "level=error" in r or r.startswith(("error:", "panic:")):
        return "errore"
    if "level=warn" in r:
        return "avviso"
    if "listening on" in r:
        return "ok"
    return "debug"


def messaggio(riga: str) -> str:
    """Il testo utile di una riga di Ollama (`time=… level=INFO source=… msg="…" chiave=valore`)."""
    m = re.search(r'msg="((?:[^"\\]|\\.)*)"(.*)$', riga) or re.search(r"msg=(\S+)(.*)$", riga)
    if not m:
        return riga
    resto = m.group(2).strip()
    return m.group(1) + (f" ({resto})" if resto else "")


def spiega_errore(righe: list[str], porta: int) -> str:
    """Una spiegazione in italiano a partire dalle ultime righe scritte da Ollama."""
    basso = "\n".join(righe).lower()
    if "address already in use" in basso or "only one usage of each socket" in basso:
        return (f"La porta {porta} è già occupata da un altro programma (forse un altro Ollama, ad esempio il servizio "
                "di sistema, che però non risponde): chiudilo, oppure cambia porta nell'indirizzo (es. "
                f"http://127.0.0.1:{porta + 1}).")
    if "permission denied" in basso or "access is denied" in basso:
        return "Permessi insufficienti: Ollama non riesce a scrivere nella sua cartella dei modelli."
    if "no space left" in basso:
        return "Il disco è pieno: elimina qualche modello o libera spazio."
    utili = [messaggio(r) for r in righe if r.strip() and livello_riga(r) is not None][-3:]
    return ("Ultime righe: " + " | ".join(utili)) if utili else "Ollama non ha scritto niente nel registro."


__all__ = ["ProcessoOllama", "come_fermarlo", "livello_riga", "messaggio", "processi", "spiega_errore", "termina"]
