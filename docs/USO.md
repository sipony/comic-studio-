# Guida d'uso

## 1. Primo avvio

1. Avvia ComfyUI come fai di solito.
2. Avvia Comic Studio (`avvia.bat`, `avvia.command` o `./avvia.sh`). Si apre il browser.
3. Il programma cerca ComfyUI da solo e controlla il sistema. In alto a destra vedi lo stato:
   pallino verde = connesso, con il nome della GPU e la VRAM.

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
   - **Tratti fissi**, in inglese: ciò che non cambia mai, come capelli, corporatura e vestiti
     (es. `old man, fat, white hair, white mustache, blue police uniform`).
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

## 5. La console

In basso c'è sempre la console: tutti i messaggi del programma, di ComfyUI e, in futuro, dell'addestramento.

- **Normale / Problemi / Dettagli** filtra i messaggi (Dettagli mostra anche i dati tecnici degli errori)
- la barra mostra il lavoro in corso con la percentuale; il pulsante ⏹ lo annulla
- trascina il bordo superiore per ingrandirla, fai clic su *Console* per chiuderla
- il pulsante copia mette le righe visibili negli appunti: utile per chiedere aiuto

## Prossimi step

Didascalie, Addestramento e Fumetto arrivano con le prossime versioni (vedi [SVILUPPO.md](SVILUPPO.md)).
