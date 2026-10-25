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
}

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
  | EventoDidascalie;

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
