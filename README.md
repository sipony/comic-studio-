# Comic Studio

Programma per creare fumetti con personaggi coerenti usando ComfyUI.
Da un'immagine di riferimento per ogni personaggio arriva alle tavole finite in quattro step:

| Step | Cosa fa | Stato |
| --- | --- | --- |
| **Sistema** | Trova ComfyUI da solo, controlla hardware, componenti, aggiornamenti e dà consigli per la tua GPU | ✅ PR 1 |
| **Personaggi** | Nome, trigger word, tratti fissi e immagine di riferimento di ogni personaggio | ✅ PR 1 |
| **1 · Dataset** | Genera con ComfyUI decine di immagini varie di ogni personaggio, con i workflow che scegli, e tiene le migliori | ✅ PR 2 |
| **2 · Didascalie** | Tag automatici (WD14 e prompt), trigger word, pulizia dei tratti fissi, zip del dataset | ✅ PR 3 |
| **3 · Addestramento** | Addestra un LoRA per personaggio con kohya sd-scripts, con log e grafico della loss | PR 4 |
| **4 · Fumetto** | Scene con più personaggi (un LoRA ciascuno), balloon e tavole | PR 5 |

Funziona su **Windows, macOS e Linux**. L'interfaccia si apre nel browser.

## Cosa serve

- **Python 3.10 o più recente** — [python.org](https://www.python.org/downloads/) (su Windows spunta *Add python.exe to PATH*)
- **ComfyUI** installato sullo stesso computer (portable, Desktop o manuale)
- **Node.js LTS** — [nodejs.org](https://nodejs.org) — serve solo per compilare l'interfaccia al primo avvio
  e dopo ogni aggiornamento. In alternativa scarica il pacchetto già compilato `comic-studio-pronto`
  dalla scheda *Actions* del repository.
- **Git** — consigliato, per scaricare gli aggiornamenti e per il controllo degli aggiornamenti di ComfyUI

## Avvio

| Sistema | Come |
| --- | --- |
| Windows | doppio clic su `avvia.bat` |
| macOS | doppio clic su `avvia.command` (la prima volta: tasto destro → Apri) |
| Linux | `./avvia.sh` |

Il primo avvio prepara da solo l'ambiente Python e compila l'interfaccia (1-2 minuti), poi apre il browser
su <http://127.0.0.1:8765>. Gli avvii successivi sono immediati; le librerie vengono controllate e aggiornate
una volta al giorno.

Opzioni utili (da aggiungere al comando):

- `--porta 9000` usa un'altra porta
- `--host 0.0.0.0` lo rende raggiungibile dagli altri computer della rete (senza password: solo in reti fidate)
- `--no-browser` non apre il browser
- `--aggiorna` forza la reinstallazione di librerie e interfaccia

## Dove finiscono i file

Impostazioni e progetti stanno nella cartella `ComicStudio` della tua cartella utente
(per esempio `C:\Users\<nome>\ComicStudio`). Si può cambiare con la variabile d'ambiente `COMIC_STUDIO_HOME`.
I progetti eliminati vanno in `ComicStudio/progetti/.cestino`, non vengono cancellati.

## Aggiornare

```
git pull
```

poi riavvia: librerie e interfaccia si aggiornano da sole.

## Documentazione

- [docs/SVILUPPO.md](docs/SVILUPPO.md) — roadmap, stato di ogni PR e decisioni prese
- [docs/ARCHITETTURA.md](docs/ARCHITETTURA.md) — come è fatto il programma, API ed eventi
- [docs/USO.md](docs/USO.md) — guida d'uso passo passo

## Sviluppo

```
# backend
python -m venv .venv && .venv/bin/pip install -r backend/requirements-dev.txt
cd backend && ../.venv/bin/python -m pytest
../.venv/bin/python -m app --no-browser          # server su :8765

# interfaccia con ricarica automatica (in un altro terminale)
cd frontend && npm ci && npx ng serve            # http://localhost:4200, /api inoltrato a :8765
```

Licenza MIT.
