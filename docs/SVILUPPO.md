# Sviluppo di Comic Studio

Diario e roadmap del progetto. Si aggiorna a ogni PR: cosa è stato fatto, cosa manca, perché si è scelto così.

## Obiettivo

Un programma con interfaccia grafica, per Windows, macOS e Linux, che porta da alcune immagini di riferimento
a un fumetto con personaggi coerenti, comandando ComfyUI e un trainer di LoRA. Il flusso è a step, con
la massima libertà su workflow, modelli e parametri, una console con tutti i log e barre di avanzamento.

## Roadmap

| PR | Contenuto | Stato |
| --- | --- | --- |
| 1 | Base: backend, interfaccia, progetti e personaggi, ricerca automatica di ComfyUI, controllo del sistema, console e avanzamento, avvio multipiattaforma, CI | ✅ questa PR |
| 2 | Step 1 Dataset: caricamento e analisi dei workflow (formato UI e API), associazione dei nodi, varianti, generazione con avanzamento, galleria, selezione automatica per somiglianza | da fare |
| 3 | Step 2 Didascalie: tagger WD14, trigger word, tabella delle frequenze dei tag, modifica per immagine | da fare |
| 4 | Step 3 Addestramento: installazione di kohya sd-scripts, preset per VRAM, parametri avanzati, log e grafico della loss, test delle epoche, scelta del LoRA | da fare |
| 5 | Step 4 Fumetto: storia per pagine e vignette, scene con più personaggi (LoRA per zona + pose), balloon, tavole | da fare |
| 6 | Costruttore di workflow: scelta di checkpoint (riconoscimento Pony / Illustrious / SDXL / Flux), LoRA, IPAdapter, ControlNet e di ogni parametro di ogni nodo | da fare |
| 7 | Aggiornamenti con un clic (ComfyUI, custom node, librerie) con conferma esplicita | da fare |

## Decisioni

**Perché un LoRA per personaggio e non solo IPAdapter.** Le prove fatte prima del programma (workflow ComfyUI
con IPAdapter, maschere regionali, style transfer) hanno mostrato che IPAdapter regge un personaggio alla
volta, ma con due personaggi e più IPAdapter impilati i tratti si mescolano (età, corporatura, colori) e lo
stile si appiattisce. Con un LoRA per personaggio il personaggio diventa una parola (trigger word) che il
modello conosce: volto, corporatura, vestiti e stile restano stabili in ogni vignetta.

**Dataset con un solo personaggio per immagine.** Per addestrare il LoRA ogni immagine del dataset deve
contenere solo quel personaggio, altrimenti il LoRA impara due persone mescolate. Le scene con più
personaggi si fanno nello Step 4, caricando i LoRA di tutti i presenti, ognuno applicato alla sua zona.

**Angular + FastAPI.** L'interfaccia è in Angular (scelta dell'utente: interfaccia ricca, usabile anche da un
altro computer della rete). Il lavoro vero è in Python, lo stesso linguaggio di ComfyUI e kohya. Il backend
serve l'interfaccia compilata, quindi per *usare* il programma basta Python; Node.js serve solo per compilarla.

**kohya sd-scripts come trainer.** Si comanda bene da programma (riga di comando, configurazione TOML), a
differenza di OneTrainer che è pensato per la sua interfaccia.

**Aggiornamenti: si segnalano, non si installano da soli.** Un aggiornamento di ComfyUI o di un custom node può
rompere i workflow: il programma li rileva e li mostra, l'installazione arriverà (PR 7) solo con conferma.

**Eliminazioni nel cestino.** Progetti e personaggi eliminati vengono spostati in `progetti/.cestino`.

## PR 1 — Base del programma

Fatto:

- **Backend FastAPI** (`backend/app`)
  - impostazioni in `~/ComicStudio/impostazioni.json` (`COMIC_STUDIO_HOME` per cambiarla)
  - progetti e personaggi su disco, con validazione della trigger word (3-24 caratteri, unica nel progetto,
    no parole che il modello conosce già) e suggerimento automatico; immagine di riferimento convertita in PNG
  - **ricerca di ComfyUI**: porte note (8188, 8000, …) con il percorso letto da `/system_stats`, processi
    attivi, configurazione di ComfyUI Desktop, cartelle tipiche di Windows / macOS / Linux; riconosce portable,
    Desktop e installazioni manuali; si avvia da sola al primo avvio e sceglie l'installazione migliore
  - **client ComfyUI** asincrono: stato, elenco modelli, caricamento immagini, esecuzione di un workflow con
    avanzamento via WebSocket e messaggi d'errore leggibili (pronto per lo Step 1)
  - **gestore dei lavori**: log, avanzamento, annullamento, lavori GPU uno alla volta; eventi a tutti i client
    via WebSocket `/api/eventi`
  - **controllo del sistema**: GPU/VRAM, RAM, disco; Python, Git, ComfyUI, custom node necessari (anche se
    presenti ma non caricati), modelli di supporto (IPAdapter, CLIP Vision, ControlNet); analisi dei
    checkpoint (famiglia Pony / Illustrious / NoobAI / SDXL / Flux e precisione letti dall'intestazione
    safetensors, GGUF); aggiornamenti disponibili (git di ComfyUI, dei custom node e del programma, ultima
    release di ComfyUI, librerie); consigli in base all'hardware (fp8 e impostazioni con 8 GB, GGUF per Flux,
    fp16 al posto di fp32, avvisi su RAM, disco, GPU di portatili, Mac)
- **Interfaccia Angular 22 + Material** (`frontend/`), tema scuro
  - barra in alto con lo stato di ComfyUI e della GPU; menu degli step
  - pagina **Sistema**: controllo completo e connessione (installazioni trovate, impostazioni manuali)
  - pagine **Progetti** e **Personaggi** (immagine di riferimento trascinabile, trigger word, tratti fissi)
  - **console** sempre visibile: filtri (normale / problemi / dettagli), ricerca, copia, ridimensionabile,
    con il lavoro in corso, la sua barra di avanzamento e il pulsante per annullarlo
  - segnaposto degli step 1-4 con la descrizione di cosa faranno
- **Avvio** `avvia.bat` / `avvia.command` / `avvia.sh` → `avvio.py`: crea l'ambiente Python, installa e
  aggiorna le librerie (una volta al giorno), compila l'interfaccia se manca o è cambiata, avvia e apre il browser
- **CI GitHub Actions**: test del backend su Windows, macOS e Linux, build e test dell'interfaccia, pacchetto
  `comic-studio-pronto` già compilato a ogni push su `main`
- **Sicurezza**: il server ascolta solo su questo computer e accetta solo richieste indirizzate a `localhost`
  (protezione dal DNS rebinding); `--host 0.0.0.0` lo apre alla rete, con un avviso
- **Test**: 30 test backend (ricerca, progetti, lavori, client ComfyUI contro un ComfyUI simulato, API,
  WebSocket, controllo del sistema, aggiornamenti git, host non consentiti), 4 test dell'interfaccia; collaudo dell'interfaccia
  con Playwright su desktop e telefono

Non ancora verificato: il programma non è stato provato su una GPU vera né con un ComfyUI reale, solo con
un ComfyUI simulato che risponde come l'API vera.

Prossimo passo: PR 2, Step 1 Dataset.
