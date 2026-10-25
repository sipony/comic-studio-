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
  creato: number;
  iniziato: number | null;
  finito: number | null;
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
  | { tipo: 'benvenuto'; comfy: StatoComfy; lavori: Lavoro[]; ts?: number }
  | EventoDataset
  | EventoDidascalie
  | EventoAddestramento
  | EventoFumetto
  | { tipo: 'kohya'; dati: StatoKohya; ts: number }
  | { tipo: 'chiusura'; ts: number }
  | { tipo: 'ia'; dati: StatoIA; ts: number };

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
  analisi: { ruoli: Ruoli; candidati: Record<Ruolo, string[]>; checkpoint: string | null; lora: string[]; nodi: NodoAnalisi[]; avvisi: string[] };
  workflow: Record<string, { class_type: string; inputs: Record<string, unknown>; _meta?: { title?: string } }>;
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
  varianti: Varianti;
  modifiche: Record<string, Record<string, unknown>>;
  quantita: number;
  da_tenere: number;
}

export interface RiepilogoDataset {
  totale: number;
  tenute: number;
  scartate: number;
  da_decidere: number;
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
}

export interface EsempioPrompt {
  inquadratura: string;
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
  azione: 'nuova' | 'stato' | 'elenco';
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
  modello_presente: boolean;
  eseguibile: string | null;
  portatile: boolean;
  errore: string | null;
  pronta: boolean;
  consigliati?: { nome: string; descrizione: string; gb: number }[];
  impostazioni?: { tipo: string; url: string; modello: string; libera_gpu: boolean; chiave_impostata: boolean };
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
