// Tipi condivisi con il backend (vedi backend/app).

export type Livello = 'debug' | 'info' | 'ok' | 'avviso' | 'errore';
export type StatoLavoro = 'in_coda' | 'in_corso' | 'completato' | 'errore' | 'annullato';
export type Esito = 'ok' | 'avviso' | 'errore' | 'info';
export type Genere = '1girl' | '1boy' | '1other';

export interface RigaLog {
  tipo: 'log';
  livello: Livello;
  msg: string;
  lavoro: string | null;
  ts: number;
  /** la riga dice quale workflow il lavoro ha mandato a ComfyUI: si può vedere il grafo */
  grafo?: boolean;
}

export interface Lavoro {
  id: string;
  tipo: string;
  titolo: string;
  progetto: string | null;
  stato: StatoLavoro;
  progresso: number;
  testo: string;
  errore: string | null;
  /** errore riconoscibile: 'ia_non_pronta' quando manca Ollama, il modello o il server dell'IA */
  codice?: string | null;
  creato: number;
  iniziato: number | null;
  finito: number | null;
  anteprima?: number;          // numero dell'ultima anteprima (0 = nessuna)
  annullando?: boolean;
  /** quante volte ha mandato un workflow a ComfyUI (0 = mai) */
  workflow?: number;
}

export interface StatoComfy {
  connesso: boolean;
  url: string | null;
  cartella: string | null;
  versione: string | null;
  gpu: string | null;
  vram_totale: number | null;
  vram_libera: number | null;
  errore: string | null;
  in_avvio: boolean;
  avviato_da_noi: boolean;
  pid: number | null;
  avvio_automatico: boolean;
}

export interface Installazione {
  cartella: string;
  codice: string | null;
  origine: string;
  tipo: string;
  url: string | null;
  versione: string | null;
  modelli: Record<string, number>;
}

export interface Impostazioni {
  comfy_url: string | null;
  comfy_dir: string | null;
  cartella_progetti: string;
  ultimo_progetto: string | null;
  avvio_automatico: boolean;
  argomenti_comfy: string;
  comando_comfy: string | null;
  attesa_avvio: number;
}

export type ImpostazioniAvvio = Partial<Pick<Impostazioni,
  'avvio_automatico' | 'argomenti_comfy' | 'comando_comfy' | 'attesa_avvio'>>;

export interface VoceControllo {
  categoria: string;
  nome: string;
  esito: Esito;
  dettaglio: string;
  azione: string | null;
  link: string | null;
}

export interface GpuInfo {
  nome: string;
  tipo?: string;
  vram_totale: number | null;
  vram_libera: number | null;
  driver?: string;
}

export interface InfoModello {
  file: string;
  cartella: string;
  dimensione: number;
  dimensione_gb: number;
  formato: string;
  famiglia: string | null;
  precisione: string | null;
  quantizzato: boolean;
}

export interface Rapporto {
  hardware: {
    sistema: string;
    architettura: string;
    cpu: string;
    core: number;
    thread: number;
    ram_totale: number;
    ram_libera: number;
    gpu: GpuInfo[];
    apple_silicon: boolean;
    dischi: { cartella: string; libero: number; totale: number }[];
  };
  voci: VoceControllo[];
  consigli: string[];
  modelli: InfoModello[];
  aggiornamenti_controllati: boolean;
  riepilogo: Record<Esito, number>;
}

export interface Sistema {
  versione: string;
  impostazioni: Impostazioni;
  comfy: StatoComfy;
  installazioni: Installazione[];
  ricerca_in_corso: boolean;
  rapporto: Rapporto | null;
}

export interface Personaggio {
  id: string;
  nome: string;
  trigger: string;
  genere: Genere;
  descrizione: string;
  storia: string;
  adulto: boolean | null;
  riferimento: string | null;
  /** se il riferimento è una proposta di Comic Studio: come è stata generata */
  origine?: RicettaProposta | null;
  /** impostazioni delle prossime proposte cambiate dal grafo della console */
  scelte_proposte?: RicettaProposta | null;
  creato: number;
}

export interface Progetto {
  id: string;
  nome: string;
  descrizione: string;
  creato: number;
  modificato: number;
  personaggi: Personaggio[];
}

export type Evento =
  | RigaLog
  | { tipo: 'avanzamento'; lavoro: string; progresso: number; testo: string; ts: number }
  | { tipo: 'lavoro'; lavoro: string; dati: Lavoro; ts: number }
  | { tipo: 'comfy'; dati: StatoComfy; ts: number }
  | { tipo: 'installazioni'; dati: Installazione[]; ts: number }
  | { tipo: 'diagnostica'; dati: Rapporto; ts: number }
  | { tipo: 'benvenuto'; comfy: StatoComfy; lavori: Lavoro[]; componenti?: StatoComponenti | null; ts?: number }
  | { tipo: 'componenti'; dati: StatoComponenti; ts: number }
  | { tipo: 'workflow'; lavoro: string; n: number; ts: number }
  | EventoDataset
  | EventoDidascalie
  | EventoAddestramento
  | EventoFumetto
  | { tipo: 'kohya'; dati: StatoKohya; ts: number }
  | { tipo: 'chiusura'; ts: number }
  | { tipo: 'ia'; dati: StatoIA; ts: number }
  | { tipo: 'proposte'; progetto: string; personaggio: string; ts: number }
  | { tipo: 'anteprima'; lavoro: string; n: number; finale: boolean; ts: number }
  | { tipo: 'personaggi'; progetto: string; personaggio: string; ts: number };

export const GENERI: { valore: Genere; etichetta: string }[] = [
  { valore: '1girl', etichetta: 'Donna (1girl)' },
  { valore: '1boy', etichetta: 'Uomo (1boy)' },
  { valore: '1other', etichetta: 'Altro (1other)' },
];

export function gb(byte: number | null | undefined, decimali = 0): string {
  if (byte == null) return '—';
  return `${(byte / 1024 ** 3).toFixed(decimali)} GB`;
}

// ------------------------------------------------------------ Step 1: dataset

export type Ruolo = 'riferimento' | 'positivo' | 'negativo' | 'seme' | 'latente' | 'salva';
export type Ruoli = Record<Ruolo, string | null>;

export const RUOLI: { chiave: Ruolo; etichetta: string; aiuto: string }[] = [
  { chiave: 'riferimento', etichetta: 'Immagine di riferimento', aiuto: 'LoadImage che riceve il riferimento del personaggio' },
  { chiave: 'positivo', etichetta: 'Prompt positivo', aiuto: 'Nodo di testo dove va il prompt di ogni variante' },
  { chiave: 'negativo', etichetta: 'Prompt negativo', aiuto: 'Nodo di testo del prompt negativo' },
  { chiave: 'seme', etichetta: 'Seme (sampler)', aiuto: 'KSampler a cui cambiare il seme a ogni immagine' },
  { chiave: 'latente', etichetta: 'Dimensioni', aiuto: 'Nodo con larghezza e altezza (Empty Latent Image)' },
  { chiave: 'salva', etichetta: 'Immagine finale', aiuto: 'SaveImage o PreviewImage da cui prendere il risultato' },
];

export interface RiassuntoWorkflow {
  id: string;
  nome: string;
  origine: string;
  creato: number;
  ruoli: Ruoli;
  avvisi: string[];
  nodi: number;
  checkpoint: string | null;
  lora: string[];
  parametri: Record<string, unknown> | null;
}

export interface NodoAnalisi {
  id: string;
  classe: string;
  titolo: string;
  valori: Record<string, unknown>;
}

export interface DettaglioWorkflow extends RiassuntoWorkflow {
  analisi: {
    ruoli: Ruoli; candidati: Record<Ruolo, string[]>; checkpoint: string | null; lora: string[]; nodi: NodoAnalisi[]; avvisi: string[];
    /** il campionatore parte dall'immagine di riferimento: posa e inquadratura sarebbero sempre le sue */
    img2img?: { campionatore: string; codifica: string; denoise: number | null } | null;
    /** IPAdapter, PuLID… che prendono l'aspetto dal riferimento */
    guide?: string[];
  };
  workflow: Record<string, { class_type: string; inputs: Record<string, unknown>; _meta?: { title?: string } }>;
}

/** Cosa succede al workflow staccando dei nodi. */
export interface EsitoEsclusione {
  ok: boolean;
  richiesti: string[];
  esclusi: string[];
  automatici: { nodo: string; titolo: string; perche: string }[];
  collegamenti: { nodo: string; titolo: string; ingresso: string; da: string | null; da_titolo: string | null; testo: string }[];
  problemi: string[];
  tipi_da_comfy: boolean;
}

export interface Inquadratura {
  nome: string;
  testo: string;
  larghezza: number;
  altezza: number;
  quota: number;
  con_posa: boolean;
}

export interface Varianti {
  inquadrature: Inquadratura[];
  angolazioni: string[];
  espressioni: string[];
  pose: string[];
  sfondi: string[];
}

export interface ConfigDataset {
  workflow: string | null;
  ruoli: Partial<Ruoli> | null;
  prompt_positivo: string;
  prompt_negativo: string;
  tag_qualita: string | null;
  tag_qualita_negativi: string | null;
  /** {stile}: tag di stile (presi dalle proposte, se ci sono) */
  stile?: string;
  /** {aspetto}: vestiti, capelli, accessori letti dal tagger sull'immagine di riferimento */
  aspetto?: string;
  varianti: Varianti;
  modifiche: Record<string, Record<string, unknown>>;
  /** con un workflow img2img: pose dalle varianti (da zero) o composizione del riferimento */
  composizione?: 'libera' | 'riferimento';
  /** nodi del workflow staccati per questo personaggio (Comic Studio ricollega il resto) */
  disattivati?: string[];
  /** pose guidate (ControlNet OpenPose con gli scheletri della libreria) */
  pose?: PoseGuidate;
  quantita: number;
  da_tenere: number;
}

export interface PoseGuidate {
  attive: boolean;
  /** null = il primo ControlNet OpenPose trovato */
  controlnet: string | null;
  /** id delle pose scelte; vuoto = tutte */
  pose: string[];
  specchiate: boolean;
  forza: number;
  fine: number;
}

export interface ControlnetDataset {
  elenco: { nome: string; architettura: string | null; compatibile: boolean | null }[];
  automatico: string | null;
  checkpoint: string | null;
  serve: string;
}

export interface Posa {
  id: string;
  nome: string;
  tag: string;
  vista: string;
  di_spalle: boolean;
  figura_intera: boolean;
  specchiata: boolean;
}

export interface RiepilogoDataset {
  totale: number;
  tenute: number;
  scartate: number;
  da_decidere: number;
  /** spazio occupato da immagini e anteprime */
  byte?: number;
  cestino?: { immagini: number; byte: number };
}

export type StatoImmagine = 'tenuta' | 'scartata' | null;

export interface ImmagineDataset {
  file: string;
  numero: number;
  inquadratura: string;
  variante: string;
  prompt: string;
  seme: number | null;
  larghezza: number | null;
  altezza: number | null;
  creato: number;
  stato: StatoImmagine;
  manuale: boolean;
  punteggio: number | null;
  /** id della posa guidata, se c'era */
  posa?: string;
}

export interface EsempioPrompt {
  inquadratura: string;
  posa?: string | null;
  dimensioni: string;
  positivo: string;
  negativo: string;
}

export interface ParametriIntegrato {
  checkpoint: string;
  ipadapter: string;
  clip_vision: string;
  lora_stile: string | null;
  forza_stile: number;
  peso_ipadapter: number;
  fine_ipadapter: number;
  passi: number;
  cfg: number;
  sampler: string;
  scheduler: string;
}

export type SpecIngresso = [unknown, Record<string, unknown>?];
export interface SpecNodo {
  input: { required?: Record<string, SpecIngresso>; optional?: Record<string, SpecIngresso> };
  display_name?: string;
}

export interface EventoDataset {
  tipo: 'dataset';
  progetto: string;
  personaggio: string;
  azione: 'nuova' | 'stato' | 'elenco' | 'config';
  immagine?: ImmagineDataset;
  ts: number;
}

// ------------------------------------------------------------ Step 2: didascalie

export type ModalitaDidascalie = 'tagger' | 'prompt' | 'entrambi';

export interface ConfigDidascalie {
  modalita: ModalitaDidascalie;
  modello: string;
  soglia: number;
  togli_tratti_fissi: boolean;
  rimossi: string[];
  aggiunti: string[];
  sostituzioni: Record<string, string>;
  massimo_tag: number;
  tag_stile: string;
}

export interface RigaDidascalia {
  file: string;
  numero: number;
  auto: string;
  testo: string;
  manuale: boolean;
  analizzata: boolean;
  creato: number;
}

export interface FrequenzaTag {
  tag: string;
  conteggio: number;
  quota: number;
  probabilita: number;
  rimosso: boolean;
  fisso: boolean;
  suggerito: boolean;
  sostituito: string | null;
}

export interface StatoDidascalie {
  config: ConfigDidascalie;
  immagini: RigaDidascalia[];
  frequenze: FrequenzaTag[];
  totale: number;
  analizzate: number;
  da_selezione: boolean;
  trigger: string;
}

export interface EventoDidascalie {
  tipo: 'didascalie';
  progetto: string;
  personaggio: string;
  ts: number;
}

// ------------------------------------------------------------ Step 3: addestramento

export type Preset = '8gb' | 'equilibrato' | 'qualita' | 'personalizzato';

export interface ConfigAddestramento {
  preset: Preset;
  checkpoint: string | null;
  rank: number;
  alpha: number;
  learning_rate: number;
  allena_text_encoder: boolean;
  learning_rate_te: number;
  ottimizzatore: 'Adafactor' | 'AdamW8bit' | 'AdamW' | 'Prodigy';
  scheduler: 'constant_with_warmup' | 'cosine' | 'cosine_with_restarts' | 'linear' | 'constant';
  warmup: number;
  epoche: number;
  passi_obiettivo: number;
  ripetizioni: number | null;
  risoluzione: number;
  batch: number;
  fp8: boolean;
  gradient_checkpointing: boolean;
  mescola_didascalie: boolean;
  noise_offset: number;
  min_snr_gamma: number | null;
  seme: number;
  argomenti_extra: string;
}

export interface EpocaLora {
  epoca: number;
  file: string;
  dimensione: number;
  creato: number;
  ultima?: boolean;
}

export interface StatoAddestramento {
  lora_finale: string | null;
  epoca_finale: number | null;
  origine: 'addestrato' | 'esistente' | null;
  ultimo_avvio: number | null;
  ultima_durata: number | null;
  ultimo_esito: string | null;
  test: Record<string, { immagini: string[]; punteggio: number | null }>;
  prompt_test: string[];
}

export interface RiassuntoAddestramento {
  config: ConfigAddestramento;
  stato: StatoAddestramento;
  epoche: EpocaLora[];
  loss: [number, number][];
  immagini: number;
  ripetizioni: number | null;
  passi_totali: number;
  preset_consigliato: Preset;
  checkpoint_suggerito: string | null;
  trigger: string;
}

export interface StatoKohya {
  installato: boolean;
  cartella: string;
  piattaforma: 'cuda' | 'mps' | 'cpu';
  gpu?: string | null;
  torch?: string;
  cuda?: boolean;
  mps?: boolean;
  commit?: string | null;
  errore?: string;
}

export interface EventoAddestramento {
  tipo: 'addestramento';
  progetto: string;
  personaggio: string;
  punto?: [number, number];
  passo?: number;
  totale?: number;
  epoca?: number;
  epoche?: number;
  velocita?: string;
  rimanente?: string;
  epoche_cambiate?: boolean;
  test?: boolean;
  ts: number;
}

// ------------------------------------------------------------ Step 4: fumetto

export type FormatoVignetta = 'larga' | 'alta' | 'quadrata';
export type PosizioneBalloon = 'auto' | 'alto-sx' | 'alto-dx' | 'basso-sx' | 'basso-dx';

export interface Dialogo {
  chi: string;
  testo: string;
  posizione: PosizioneBalloon;
}

export interface Vignetta {
  id: string;
  formato: FormatoVignetta;
  personaggi: string[];
  azione: string;
  descrizione?: string;
  analisi?: { chiave: string; dati: Record<string, unknown> } | null;
  rafforza?: string[];
  dialoghi: Dialogo[];
  seme: number | null;
}

export interface Pagina {
  id: string;
  vignette: Vignetta[];
}

export interface ImpostazioniFumetto {
  checkpoint: string | null;
  lora_stile: string | null;
  forza_stile: number;
  forza_personaggio: number;
  positivo: string;
  negativo: string;
  tag_qualita: string | null;
  tag_qualita_negativi: string | null;
  passi: number;
  cfg: number;
  sampler: string;
  scheduler: string;
  ripasso: number;
  font: string | null;
  larghezza_pagina: number;
  margine: number;
}

export interface Fumetto {
  titolo: string;
  impostazioni: ImpostazioniFumetto;
  pagine: Pagina[];
}

export interface VersioneVignetta {
  file: string;
  seme: number;
  creato: number;
  prompt: string;
  aderenza?: Aderenza | null;
}

export interface Aderenza {
  trovati: string[];
  mancanti: string[];
  non_verificabili: string[];
  punteggio: number | null;
}

export interface PromptScena {
  globale: string;
  per_personaggio: Record<string, string>;
  negativo: string;
  chiave: string[];
  personaggi: string[];
  altri_soggetti: number;
  non_rappresentabile: string[];
  sessuale: boolean;
}

export interface TrattiRicavati {
  descrizione: string;
  genere: Genere | null;
  adulto: boolean | null;
  eta_apparente: string;
  frase: string;
  non_rappresentabile: string[];
}

export interface StatoIA {
  tipo: 'ollama' | 'openai' | 'nessuna';
  url: string | null;
  modello: string | null;
  raggiungibile: boolean;
  versione: string | null;
  modelli: string[];
  /** byte di ogni modello scaricato (solo Ollama) */
  dimensioni?: Record<string, number>;
  modello_presente: boolean;
  eseguibile: string | null;
  portatile: boolean;
  errore: string | null;
  pronta: boolean;
  /** il processo di Ollama */
  in_avvio?: boolean;
  avviato_da_noi?: boolean;
  pid?: number | null;
  /** acceso ma non da Comic Studio: da chi */
  esterno?: string | null;
  /** fermato con «Ferma»: non si riaccende da solo */
  fermato?: boolean;
  avvio_automatico?: boolean;
  /** il server compatibile OpenAI non risponde, ma Ollama c'è */
  suggerisci_ollama?: boolean;
  consigliati?: { nome: string; descrizione: string; gb: number }[];
  impostazioni?: { tipo: string; url: string; modello: string; libera_gpu: boolean; chiave_impostata: boolean; avvio_automatico?: boolean };
}

/** Dove gira un modello su questo computer. */
export type DoveIA = 'gpu' | 'misto' | 'cpu' | 'troppo';

export interface VarianteIA {
  nome: string;
  alias: string[];
  quant: string;
  gb: number;
  memoria_gb: number;
  stimata: boolean;
  installato: boolean;
  attuale: boolean;
  dove: DoveIA;
  nota: string;
  punteggio: number;
}

export interface RigaCatalogoIA {
  famiglia: string;
  dimensione: string;
  parametri: number;
  attivi: number | null;
  descrizione: string;
  varianti: VarianteIA[];
  migliore: string;
  punteggio: number;
  dove: DoveIA;
  consigliato?: boolean;
  migliore_in_assoluto?: boolean;
}

export interface CatalogoIA {
  hardware: { gpu: string | null; vram_gb: number; ram_gb: number; apple: boolean; memoria_gpu: number; memoria_ram: number };
  aggiornato: number | null;
  online: boolean;
  da_aggiornare: boolean;
  famiglie: string[];
  modelli: RigaCatalogoIA[];
  attuale: string | null;
  stato: StatoIA;
}

export interface ImmaginiVignetta {
  versioni: VersioneVignetta[];
  scelta: number | null;
}

export interface StatoFumetto {
  fumetto: Fumetto;
  immagini: Record<string, ImmaginiVignetta>;
  lora: Record<string, string | null>;
}

export interface EventoFumetto {
  tipo: 'fumetto';
  progetto: string;
  vignetta: string;
  ts: number;
}

export type InquadraturaProposta = 'figura_intera' | 'mezzo_busto' | 'primo_piano';

export interface ConfigProposte {
  checkpoint: string;
  numero: number;
  inquadratura: InquadraturaProposta;
  stile: string;
  extra: string;
  negativo?: string;
  passi?: number;
  cfg?: number;
  sampler?: string;
  scheduler?: string;
  lora_stile?: string | null;
  forza_lora?: number;
  forza_variante?: number;
  da?: string | null;
  /** «Ho già il prompt»: il positivo usato così com'è */
  positivo?: string | null;
}

/** Come è stata generata una proposta: il dataset riparte dalle stesse scelte. */
export interface RicettaProposta {
  checkpoint: string;
  lora_stile: string | null;
  forza_lora: number;
  stile: string;
  extra: string;
  negativo: string | null;
  passi: number;
  cfg: number;
  sampler: string;
  scheduler: string;
  inquadratura: string;
  forza_variante?: number;
  positivo?: string | null;
}

export interface AnteprimaPromptProposte {
  positivo: string | null;
  negativo: string | null;
  famiglia: string;
  nota: string | null;
  proprio?: boolean;
}

/** Le scelte delle proposte da cui viene il riferimento, viste dal dataset. */
export interface OrigineDataset {
  ricetta: RicettaProposta;
  checkpoint_workflow: string | null;
  coerente: boolean;
}

export const NEGATIVO_PROPOSTE = '{negativo_qualita}, multiple views, 2girls, 2boys, crowd, cropped, out of frame, text, ' +
  'watermark, signature, bad anatomy, bad hands, extra fingers, deformed, blurry, lowres';
export const SAMPLER = ['euler_ancestral', 'euler', 'dpmpp_2m', 'dpmpp_2m_sde', 'dpmpp_sde', 'dpmpp_3m_sde', 'uni_pc', 'ddim'];
export const SCHEDULER = ['karras', 'normal', 'exponential', 'sgm_uniform', 'simple', 'beta'];
export const NOMI_FAMIGLIA: Record<string, string> = {
  pony: 'Pony', illustrious: 'Illustrious', noobai: 'NoobAI', sdxl: 'SDXL', flux: 'Flux', sd15: 'SD 1.5', sd3: 'SD 3',
};

export interface Proposta {
  file: string;
  seme: number;
  prompt: string;
  creato: number;
  da: string | null;
  scelta: boolean;
  ricetta?: RicettaProposta | null;
}

// ------------------------------------------------------------ componenti di ComfyUI (IPAdapter Plus)

export interface Componente {
  id: string;
  nome: string;
  tipo: 'nodo' | 'modello';
  descrizione: string;
  cartella: string;
  file: string;
  byte: number;
}

export interface SpazioDisco {
  cartella: string;
  libero: number;
  serve: number;
  basta: boolean;
}

export interface StatoComponenti {
  comfy_dir: string | null;
  mancanti: Componente[];
  presenti: string[];
  /** nodi sul disco che ComfyUI non carica */
  da_caricare: string[];
  spazio: SpazioDisco[];
  basta_spazio: boolean;
  totale: number;
  errore: string | null;
  /** chiederlo all'apertura (false = «non chiedere più») */
  chiedi: boolean;
  lavoro: string | null;
  comfy_avviato_da_noi: boolean;
  comfy_connesso: boolean;
  messaggio_spazio: string | null;
  gruppo?: 'ipadapter' | 'pose';
  nome?: string;
}

// ------------------------------------------------------------ grafo del workflow mandato a ComfyUI

export interface IngressoGrafo { nome: string; tipo: string; da: string; uscita: number }
export interface UscitaGrafo { nome: string; tipo: string }
export interface NodoGrafo {
  id: string;
  classe: string;
  titolo: string;
  ingressi: IngressoGrafo[];
  widget: { nome: string; valore: unknown }[];
  uscite: UscitaGrafo[];
}
export interface CollegamentoGrafo { da: string; uscita: number; a: string; ingresso: string; tipo: string }
export interface WorkflowLavoro {
  lavoro: Lavoro;
  n: number;
  riassunto: string;
  workflow: Record<string, unknown>;
  grafo: { nodi: NodoGrafo[]; collegamenti: CollegamentoGrafo[]; da_comfy: boolean };
  impostazioni: ImpostazioniGrafo;
  /** workflow salvati (proposte, dataset): dove scaricare il JSON e se è stato ricostruito */
  url_json?: string;
  ricostruito?: boolean;
  nota?: string | null;
}

export interface RigaConfrontoGrafi {
  tipo: 'solo_a' | 'solo_b' | 'collegamento' | 'passa_per' | 'valore';
  nodo_a: string | null;
  nodo_b: string | null;
  classe: string;
  titolo: string;
  campo: string | null;
  a: unknown;
  b: unknown;
  testo: string;
  solo_a?: string[];
  solo_b?: string[];
}

export interface ConfrontoGrafi {
  proposta: WorkflowLavoro;
  immagine: WorkflowLavoro;
  file_proposta: string;
  righe: RigaConfrontoGrafi[];
  evidenzia_a: Record<string, string[]>;
  evidenzia_b: Record<string, string[]>;
  uguali: boolean;
}

/** Tipo e limiti di un'impostazione di un nodo (da /object_info di ComfyUI o dagli elenchi noti). */
export interface SpecImpostazione {
  tipo: 'INT' | 'FLOAT' | 'COMBO' | 'STRING' | 'BOOLEAN' | string;
  min?: number | null;
  max?: number | null;
  step?: number | null;
  default?: unknown;
  opzioni?: string[];
  multiline?: boolean;
}
export interface CampoGrafo {
  modificabile: boolean;
  /** perché non si può cambiare, e dove si cambia */
  perche: string | null;
  spec: SpecImpostazione;
  /** valore già salvato per le prossime generazioni */
  salvato?: unknown;
}
export interface ImpostazioniGrafo {
  sorgente: { tipo: 'dataset' | 'proposte'; personaggio: string; descrizione: string } | null;
  campi: Record<string, Record<string, CampoGrafo>>;
}

/** Il dataset confrontato con la proposta scelta come riferimento. */
export interface ConfrontoListe {
  proposta: string[] | string;
  dataset: string[] | string;
  mancano: string[];
  in_piu: string[];
  ordine_ok: boolean;
  uguale: boolean;
}
export interface ConfrontoDataset {
  proposta: { file: string; prompt: string; ricetta: RicettaProposta | null };
  /** famiglia del checkpoint delle proposte (dalla ricetta, o dai tag di qualità del prompt) */
  famiglia_proposta: string | null;
  stile_proposta: string[];
  mancanti: string[];
  esempio_dataset: string | null;
  /** parti fisse del prompt (senza le varianti), tag per tag */
  prompt: ConfrontoListe & { proposta: string[]; dataset: string[] };
  negativo: ConfrontoListe & { proposta: string; dataset: string };
  /** uguale = stessi nodi, valori e catene, in più solo il riferimento; null = proposta senza ricetta */
  workflow: { uguale: boolean | null; riferimento: boolean | null; senza_riferimento?: boolean; differenze: string[] };
  righe: { voce: string; proposte: string; dataset: string; uguale: boolean | null; nota: string }[];
  coerente: boolean;
}
