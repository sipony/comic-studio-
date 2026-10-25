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
  | { tipo: 'benvenuto'; comfy: StatoComfy; lavori: Lavoro[]; ts?: number };

export const GENERI: { valore: Genere; etichetta: string }[] = [
  { valore: '1girl', etichetta: 'Donna (1girl)' },
  { valore: '1boy', etichetta: 'Uomo (1boy)' },
  { valore: '1other', etichetta: 'Altro (1other)' },
];

export function gb(byte: number | null | undefined, decimali = 0): string {
  if (byte == null) return '—';
  return `${(byte / 1024 ** 3).toFixed(decimali)} GB`;
}
