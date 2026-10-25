# Guida d'uso

## 1. Primo avvio

1. Installa Comic Studio con l'installer del tuo sistema (vedi il README) e aprilo dall'icona;
   dai sorgenti: `avvia.bat`, `avvia.command` o `./avvia.sh`. Si apre il browser.
2. Il programma cerca ComfyUI da solo: se è già aperto ci si aggancia, altrimenti **lo avvia lui** e aspetta
   che sia pronto (la prima volta può volerci qualche minuto; in console vedi cosa scrive ComfyUI).
3. Poi controlla il sistema. In alto a destra vedi lo stato: pallino giallo = in avvio, verde = connesso,
   con il nome della GPU e la VRAM.

In **Sistema → Connessione a ComfyUI** trovi i pulsanti **Avvia**, **Riavvia** (utile dopo aver installato custom
node o modelli) e **Ferma**, l'interruttore dell'avvio automatico e gli **argomenti in più** (es. `--lowvram`).
ComfyUI resta acceso anche se chiudi Comic Studio. Se usi un tuo file di avvio (es. `run_nvidia_gpu.bat`),
scrivilo in **Opzioni avanzate → Comando di avvio personalizzato**.

Se ComfyUI non viene trovato: pagina **Sistema → Connessione a ComfyUI**, inserisci l'indirizzo
(di solito `http://127.0.0.1:8188`, oppure `:8000` per l'app Desktop) e la cartella che contiene
`models`, `input` e `output`, poi **Salva e prova**.

## 2. Controllo del sistema

Pagina **Sistema → Controllo**. Le voci sono divise per categoria, con un'icona:

- ✅ a posto · ⚠️ da tenere d'occhio · ❗ da sistemare prima di proseguire · ℹ️ informazione

Per ogni problema c'è scritto cosa fare e, quando serve, il link da cui scaricare il componente.
Nel riquadro **Consigli** trovi le impostazioni più adatte alla tua scheda video (per esempio fp8 con 8 GB di VRAM).
**Ricontrolla tutto** cerca anche gli aggiornamenti (serve internet); **Controllo rapido** solo i controlli locali.

## 3. Progetto e personaggi

1. **Progetti → Nuovo progetto**: dai un nome alla storia.
2. Nella pagina **Personaggi** aggiungi ogni personaggio:
   - **Nome** e **tipo** (donna, uomo, altro)
   - **Trigger word**: una parola inventata (ne viene proposta una, il dado ne genera un'altra).
     Non usare parole vere come "police" o "girl": il modello le conosce già e si confonderebbe.
   - **Descrizione libera**: scrivi il personaggio come vuoi, anche a lungo e in italiano, poi premi
     **Ricava i tratti con l'IA**: l'IA locale ne tira fuori i tratti fissi in inglese (e il tipo). Controllali e
     premi **Salva**. La personalità e la storia restano nella descrizione, non finiscono nel prompt.
   - **Tratti fissi**, in inglese: ciò che non cambia mai, come capelli, corporatura e vestiti
     (es. `old man, fat, white hair, white mustache, blue police uniform`). Puoi anche scriverli a mano.
   - **Immagine di riferimento**: trascinala nel riquadro. Meglio un'immagine pulita, a figura intera o
     mezzo busto, su sfondo semplice.

## 4. Step 1 · Dataset

Per ogni personaggio (scegli in alto quale):

1. **Workflow** — scegline uno dalla libreria del progetto, **caricane uno** tuo (il file salvato da ComfyUI va
   bene, con ComfyUI avviato) oppure **crea quello integrato** (SDXL + IPAdapter) scegliendo checkpoint, LoRA di
   stile e modelli dagli elenchi. Il programma riconosce da solo i nodi del riferimento, dei prompt, del seme,
   delle dimensioni e dell'immagine finale: controlla in «Nodi riconosciuti» e correggi solo se serve.
   In «Parametri dei nodi» puoi cambiare qualunque valore (passi, CFG, forza dell'IPAdapter…) solo per questo personaggio.
2. **Prompt e varianti** — il prompt è un modello: `{descrizione}` diventa i tratti fissi del personaggio,
   `{variante}` cambia a ogni immagine (inquadratura, angolazione, espressione, posa, sfondo), `{qualita}` mette i
   tag giusti per il checkpoint. Sotto vedi esempi dei prompt che verranno usati.
3. **Generazione** — scegli quante immagini (80-120) e quante tenerne (20-40), poi **Genera**. Segui
   l'avanzamento qui e nella console; puoi fermarla quando vuoi.
4. **Galleria** — **Tieni le N migliori** sceglie da sola le più somiglianti al riferimento, varie e senza doppioni.
   Poi rifinisci a mano: passa sopra un'immagine e premi ✓ o ✕, oppure aprila e usa **T** (tieni), **S** (scarta)
   e le frecce. Le tue scelte manuali non vengono più toccate dalla selezione automatica.

## 5. Step 2 · Didascalie

1. Scegli il personaggio. Vengono usate le immagini che hai tenuto nello Step 1.
2. **Analizza** fa guardare le immagini al tagger WD14 (la prima volta lo scarica, circa 400 MB). Se sei offline
   scegli **Solo prompt**: i tag vengono dal prompt con cui ogni immagine è stata generata.
3. Ogni didascalia inizia con la trigger word. I **tratti fissi** della descrizione vengono tolti da soli; nella
   tabella **Tag del dataset** i tag segnati «fisso?» sono tratti dell'aspetto presenti in quasi tutte le immagini:
   **Togli i suggeriti** li toglie tutti, oppure fai clic su un tag per toglierlo o rimetterlo.
4. Se una didascalia non va, correggila a mano nel suo riquadro (torna a quella automatica con **Automatica**).
5. **Scarica il dataset** ti dà uno zip con immagini e `.txt`, utile per addestrare anche altrove.

## 6. Step 3 · Addestramento

1. **Trainer**: la prima volta premi **Installa**. Scarica kohya, PyTorch e le librerie (circa 3 GB, 10-20 minuti);
   servono Python 3.10, 3.11 o 3.12 (meglio il 3.10) e preferibilmente Git.
2. Scegli il personaggio e il **checkpoint di base**: lo stesso che userai per il fumetto.
3. Scegli il **preset**: quello «consigliato» va bene per la tua scheda (con 8 GB: «8 GB sicuro»). Nei
   **parametri avanzati** puoi cambiare tutto; il conto ti dice quanti passi farà.
4. **Addestra**: segui passi, epoche, tempo rimanente e il grafico della loss. Con 8 GB conta 1-3 ore. ComfyUI può
   restare aperto.
5. **Prova le epoche**: scegli quali (di solito sono già selezionate 4) e premi **Prova**. Confronta le immagini
   affiancate e premi **Usa questa** sull'epoca migliore: quella «consigliata» è un buon punto di partenza.
6. Hai già un LoRA addestrato altrove? Sceglilo in **Oppure usa un LoRA già addestrato**.

## 7. Step 4 · Fumetto

1. **Impostazioni**: scegli il checkpoint (lo stesso dei LoRA) ed eventualmente un LoRA di stile.
2. Scrivi le pagine: **Storia da testo → Racconto libero** per incollare tutta la storia così com'è (l'IA la divide
   in pagine e vignette, sceglie i personaggi e copia i dialoghi), **Una vignetta per riga** per il formato
   a righe, oppure aggiungi le vignette a mano a sinistra.
3. Per ogni vignetta: **formato**, **personaggi** in scena (clic per aggiungerli; il primo sta a sinistra, le
   frecce cambiano l'ordine; se non ne scegli, li trova l'IA nel testo), la **descrizione della scena** in
   linguaggio naturale, lunga quanto vuoi, ed eventuali **tag in più** in inglese, poi le **battute** con chi parla
   e dove mettere il balloon. **Trasforma in prompt** mostra cosa ha capito l'IA: la scena, cosa fa ciascun
   personaggio nella sua zona, cosa evitare e cosa non si può disegnare (suoni, odori, pensieri). Si fa comunque
   da solo quando generi, e si rifà solo se cambi il testo.
4. **Genera le mancanti** fa tutte le vignette senza immagine; sulla singola vignetta **Nuova versione** ne prova
   un'altra, **Stesso seme** rifà la stessa composizione con le modifiche al testo. Le versioni restano: clic su
   una miniatura per usarla.
   Sotto l'immagine c'è l'**aderenza**: quali elementi chiave della descrizione il tagger vede davvero
   (✓) e quali mancano (✗). **Rafforza i mancanti e rigenera** li fa pesare di più e rifà la vignetta con lo
   stesso seme.
5. A destra vedi la **tavola** con i balloon. **Esporta** ti dà il PDF o le pagine in PNG.

## 8. L'IA locale

In **Sistema → IA locale** la prima volta premi **Installa**: Comic Studio scarica Ollama (1-2 GB) e il modello
(Qwen3 8B, circa 5 GB) nella cartella `ComicStudio/strumenti/ollama`, dopo averti chiesto conferma. Tutto gira sul
tuo computer. Se hai già Ollama o LM Studio, Comic Studio usa quelli. Puoi provare l'IA con una scena di esempio e
cambiare modello (più leggero o più preciso). Prima di ogni domanda all'IA la memoria della scheda video viene
liberata, così ComfyUI e l'IA non se la contendono.

Contenuti: il testo viene tradotto in modo fedele, horror, violenza e sangue compresi. C'è un solo blocco fisso,
che non si può disattivare: niente contenuti sessuali con minorenni o personaggi dall'aspetto infantile.

## 9. La console

Per **chiudere** Comic Studio usa il pulsante ⏻ in alto a destra: puoi lasciare acceso ComfyUI o chiudere anche
quello. Riaprendo l'icona la pagina si riattiva da sola. Se qualcosa va storto all'avvio, il registro è in
`ComicStudio/comicstudio.log`.

In basso c'è sempre la console: tutti i messaggi del programma, di ComfyUI e, in futuro, dell'addestramento.

- **Normale / Problemi / Dettagli** filtra i messaggi (Dettagli mostra anche i dati tecnici degli errori)
- la barra mostra il lavoro in corso con la percentuale; il pulsante ⏹ lo annulla
- trascina il bordo superiore per ingrandirla, fai clic su *Console* per chiuderla
- il pulsante copia mette le righe visibili negli appunti: utile per chiedere aiuto

## Prossimi step

Pose guidate nelle scene di gruppo, costruttore di workflow e aggiornamenti con un clic: vedi [SVILUPPO.md](SVILUPPO.md).
