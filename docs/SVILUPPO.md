# Sviluppo di Comic Studio

Diario e roadmap del progetto. Si aggiorna a ogni PR: cosa è stato fatto, cosa manca, perché si è scelto così.

## Obiettivo

Un programma con interfaccia grafica, per Windows, macOS e Linux, che porta da alcune immagini di riferimento
a un fumetto con personaggi coerenti, comandando ComfyUI e un trainer di LoRA. Il flusso è a step, con
la massima libertà su workflow, modelli e parametri, una console con tutti i log e barre di avanzamento.

## Roadmap

| PR | Contenuto | Stato |
| --- | --- | --- |
| 1 | Base: backend, interfaccia, progetti e personaggi, ricerca automatica di ComfyUI, controllo del sistema, console e avanzamento, avvio multipiattaforma, CI | ✅ unita |
| 2 | Step 1 Dataset: caricamento e analisi dei workflow (formato UI e API), associazione dei nodi, varianti, generazione con avanzamento, galleria, selezione automatica per somiglianza | ✅ unita |
| 3 | Step 2 Didascalie: tagger WD14, trigger word, tabella delle frequenze dei tag, modifica per immagine | ✅ unita |
| 4 | Step 3 Addestramento: installazione di kohya sd-scripts, preset per VRAM, parametri avanzati, log e grafico della loss, test delle epoche, scelta del LoRA | ✅ questa PR |
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

**Somiglianza con CLIP in ONNX, senza PyTorch.** Per scegliere le immagini più somiglianti al riferimento serve
un modello visivo. PyTorch peserebbe più di 2 GB solo per questo: si usa invece il modello visivo di CLIP ViT-B/32
quantizzato (circa 90 MB) con onnxruntime, scaricato la prima volta. Se non si può scaricare (offline) si usa un
metodo semplice su colori e forma, meno preciso, e lo si dice nella console. Lo stesso runtime servirà al tagger
WD14 dello Step 2.

**Il programma gestisce prompt, seme, dimensioni e riferimento; il resto del workflow resta tuo.** Ogni workflow
viene analizzato per trovare i nodi con questi ruoli (si possono correggere a mano). Tutti gli altri valori di
ogni nodo si possono cambiare per singolo personaggio senza toccare il file originale.

**Didascalie da due fonti.** Le immagini del dataset sono generate da noi, quindi conosciamo già il prompt di
ognuna: è una fonte di tag sempre disponibile e senza download. Il tagger WD14 aggiunge ciò che il modello ha
davvero disegnato (che non sempre coincide con il prompt). Per default si usano entrambe; i tag del tagger si
salvano con la loro probabilità, così cambiare la soglia non richiede di rianalizzare.

**I tratti fissi si tolgono dalle didascalie.** Ciò che non compare nella didascalia ma è sempre presente
nell'immagine viene assorbito dalla trigger word: per questo i tratti della descrizione del personaggio
(capelli, divisa…) vengono tolti in automatico e quelli dell'aspetto presenti in quasi tutte le immagini
vengono segnalati come «fisso?».

**kohya con un ambiente Python suo.** kohya vuole versioni precise di PyTorch e delle sue librerie (Python
3.10 consigliato, `torch==2.6.0` con CUDA 12.4): vive in `<cartella dati>/strumenti/sd-scripts` con il suo
`venv`, separato da quello del programma e da quello di ComfyUI, così nessuno rompe l'altro. Si lancia
`sdxl_train_network.py` direttamente (niente `accelerate config`), leggendo l'uscita riga per riga.

**La scelta dell'epoca si fa guardando, aiutati dal punteggio.** Il programma prova alcune epoche con gli stessi
prompt e semi e calcola la somiglianza al riferimento; consiglia la prima epoca quasi buona quanto la migliore,
perché le ultime tendono a «cuocere» il LoRA. La decisione finale resta a te.

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

## PR 2 — Step 1 Dataset

Fatto:

- **Libreria dei workflow del progetto** (`backend/app/workflows.py`, `dataset.py`)
  - si carica il file salvato normalmente da ComfyUI (convertito nel formato API usando le definizioni dei
    nodi di ComfyUI: widget, `control_after_generate`, Reroute, nodi Primitive, nodi in bypass o disattivati,
    note) oppure quello esportato con «Export (API)»; nodi mancanti e subgraph sono segnalati con un messaggio chiaro
  - **workflow integrato** SDXL + IPAdapter, creato da un modulo con i modelli presenti in ComfyUI
  - **analisi automatica dei ruoli**: immagine di riferimento (il LoadImage che va all'IPAdapter), prompt
    positivo e negativo (risalendo dal sampler), seme, dimensioni, nodo finale; correggibili a mano
- **Configurazione per personaggio**, salvata da sola mentre la modifichi
  - modello di prompt con segnaposto (`{qualita}`, `{genere}`, `{descrizione}`, `{variante}`, …) e tag di
    qualità automatici in base al checkpoint (Pony `score_9…`, Illustrious `masterpiece…`, …)
  - **varianti**: inquadrature con dimensioni e quota, angolazioni, espressioni, pose, sfondi; esempi dei
    prompt che verranno generati
  - **parametri dei nodi**: qualunque valore di qualunque nodo, modificabile solo per quel personaggio
- **Generazione** come lavoro GPU: carica il riferimento in ComfyUI, crea ogni immagine con la sua variante e
  un seme nuovo, avanzamento per passo del sampler e per immagine, tempo rimanente, si ferma quando vuoi
  (interrompendo anche ComfyUI); «Genera altre» continua la numerazione, «Rifai da capo» sposta tutto nel cestino
- **Galleria** in tempo reale: filtri (tenute, da decidere, scartate), ordine per somiglianza, anteprime,
  ingrandimento con prompt e seme, tasti T / S per tenere o scartare e frecce per scorrere
- **Selezione automatica** (`somiglianza.py`): punteggio di somiglianza al riferimento con CLIP, quote per
  inquadratura, esclusione dei quasi-doppioni; le scelte fatte a mano restano
- **Test**: 47 test backend (conversione UI→API con link nei due formati, analisi su un workflow reale a 4
  vignette, applicazione dei valori, varianti e quote, selezione, valutatore ONNX con un modello di prova, flusso
  completo via API contro il ComfyUI simulato); collaudo dell'interfaccia con Playwright

Non ancora verificato: la qualità della selezione con il modello CLIP vero (qui non si può scaricare) e la
generazione su un ComfyUI reale.

## PR 3 — Step 2 Didascalie

Fatto:

- **Tagger WD14** in ONNX (`backend/app/didascalie.py`): `wd-vit-tagger-v3` scaricato al primo uso, stessa
  preparazione dell'immagine dell'originale (quadrato bianco, 448 px, BGR); salva i tag con probabilità ≥ 0,2
- **Didascalie automatiche**: `trigger, 1girl/1boy, solo, [tag sempre presenti], tag dell'immagine, [tag di stile]`
  - fonti: tagger, prompt di generazione o entrambe; soglia di sicurezza regolabile
  - tolti in automatico i tratti fissi della descrizione; tag da togliere, sostituzioni, numero massimo di tag
  - usa le immagini tenute nello Step 1 (se non ne hai scelta nessuna, tutte tranne le scartate, con avviso)
- **Tabella dei tag del dataset**: quante immagini hanno ogni tag, clic per toglierlo o rimetterlo in tutte,
  sostituzione, filtro «suggeriti» (tratti dell'aspetto presenti in almeno il 70% delle immagini) e
  «Togli i suggeriti» con un clic
- **Modifica a mano** di ogni didascalia accanto alla sua immagine, con ritorno a quella automatica
- **Scarica il dataset**: zip con immagini e `.txt`, utilizzabile con qualunque trainer (anche online);
  `esporta()` prepara la stessa cartella per lo Step 3
- Il selettore del personaggio è ora un componente comune (Dataset e Didascalie)
- **Test**: 54 test backend (tagger ONNX con un modello di prova, composizione, frequenze e suggerimenti,
  scritte a mano, esportazione e zip, flusso via API); collaudo dell'interfaccia con Playwright

Non ancora verificato: il tagger vero (da qui non si può scaricare).

## PR 4 — Step 3 Addestramento

Fatto:

- **Installazione di kohya sd-scripts con un clic** (`backend/app/addestramento.py`, `rotte_addestramento.py`):
  clona il repository (o scarica lo zip se Git manca), crea l'ambiente con un Python 3.10-3.12, installa
  PyTorch 2.6 adatto alla macchina (CUDA 12.4 con NVIDIA, MPS su Mac, CPU altrimenti) e le librerie; verifica
  che PyTorch veda la GPU. Pulsanti per aggiornare e reinstallare
- **Parametri** con preset scelto in base alla VRAM: «8 GB sicuro» (fp8, rank 16, Adafactor, solo UNet, cache del
  text encoder), «Equilibrato», «Qualità»; tutti i parametri avanzati (alpha, learning rate, ottimizzatore,
  scheduler, warmup, risoluzione, batch, ripetizioni, min SNR, noise offset, text encoder, mescola tag, argomenti
  extra); conto dei passi immagini × ripetizioni × epoche
- **Addestramento** come lavoro GPU: esporta il dataset con le didascalie, fa liberare la memoria a ComfyUI, lancia
  kohya e legge in diretta passo, epoca, velocità, tempo rimanente e loss (anche le righe di tqdm con `\r`);
  grafico della loss; si ferma terminando anche i processi figli; errori spiegati (memoria esaurita, librerie
  mancanti, GPU non vista, checkpoint rovinato); le epoche precedenti vanno nel cestino
- **Prova delle epoche** con ComfyUI: copia le epoche scelte in `models/loras/comic_studio`, genera i prompt di prova
  (modificabili) con gli stessi semi, punteggio di somiglianza e epoca consigliata; confronto affiancato
- **Scelta del LoRA finale**: copiato come `comic_studio/<trigger>.safetensors`, pronto per lo Step 4; oppure
  si usa un LoRA già esistente (per esempio addestrato online con lo zip dello Step 2)
- **Test**: 62 test backend (comando di kohya e preset, lettura dell'uscita reale di kohya, epoche, comandi di
  installazione, lettura dei processi anche nel modo di riserva per Windows, flusso completo con un kohya simulato: addestramento, errore di memoria, prova e scelta);
  collaudo dell'interfaccia con Playwright

Non ancora verificato: l'installazione e l'addestramento veri su Windows con la GPU dell'utente.

Prossimo passo: PR 5, Step 4 Fumetto.

