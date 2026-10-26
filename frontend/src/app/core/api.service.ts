import { HttpClient, HttpErrorResponse, HttpEventType } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import {
  AnteprimaPromptProposte, CatalogoIA, StatoComponenti, ConfigAddestramento, OrigineDataset, EsitoEsclusione, ConfigDataset, ConfigDidascalie, DettaglioWorkflow, Impostazioni, ImpostazioniAvvio, PromptScena, Proposta, ConfigProposte, StatoIA, Preset, RiassuntoAddestramento,
  StatoAddestramento, StatoKohya, Fumetto, ImmaginiVignetta, StatoFumetto, EsempioPrompt, Genere, ImmagineDataset, Lavoro, ParametriIntegrato, Personaggio,
  Progetto, Rapporto, RiassuntoWorkflow, RiepilogoDataset, RigaLog, Ruoli, Sistema, SpecNodo, StatoComfy, StatoDidascalie, StatoImmagine,
} from './modelli';

/** Accesso alle API REST del backend. Tutti i metodi restituiscono Promise e lanciano un Error leggibile. */
@Injectable({ providedIn: 'root' })
export class ApiService {
  private http = inject(HttpClient);

  private async chiama<T>(richiesta: Promise<T>): Promise<T> {
    try {
      return await richiesta;
    } catch (e) {
      throw new Error(messaggioErrore(e));
    }
  }

  private get<T>(url: string, params?: Record<string, string>) {
    return this.chiama(firstValueFrom(this.http.get<T>(url, { params })));
  }
  private post<T>(url: string, corpo: unknown = {}, params?: Record<string, string>) {
    return this.chiama(firstValueFrom(this.http.post<T>(url, corpo, { params })));
  }
  private patch<T>(url: string, corpo: unknown) {
    return this.chiama(firstValueFrom(this.http.patch<T>(url, corpo)));
  }
  private del(url: string) {
    return this.chiama(firstValueFrom(this.http.delete<void>(url)));
  }

  // sistema
  sistema() { return this.get<Sistema>('/api/sistema'); }
  log(n = 1000) { return this.get<RigaLog[]>('/api/log', { n: String(n) }); }
  lavori() { return this.get<Lavoro[]>('/api/lavori'); }
  annulla(id: string) { return this.post(`/api/lavori/${id}/annulla`); }
  annullaTutti() { return this.post<{ annullati: number }>('/api/lavori/annulla'); }

  // ComfyUI
  cercaComfy() { return this.post<Lavoro>('/api/comfy/cerca'); }
  usaComfy(url: string | null, cartella: string | null) {
    return this.post<StatoComfy>('/api/comfy/usa', { url, cartella });
  }
  esci(comfy: boolean) { return this.post<{ ok: boolean }>('/api/esci', { comfy }); }
  // ------------------------------------------------------------ IA locale e testo → prompt
  lavoro<T = unknown>(id: string) { return this.get<Lavoro & { risultato: T | null }>(`/api/lavori/${id}`); }
  statoIA() { return this.get<StatoIA>('/api/ia'); }
  impostaIA(dati: ImpostazioniIA) {
    return this.post<StatoIA>('/api/ia/impostazioni', dati);
  }
  catalogoIA() { return this.get<CatalogoIA>('/api/ia/catalogo'); }
  aggiornaCatalogoIA(famiglia?: string) { return this.post<Lavoro>('/api/ia/catalogo/aggiorna', famiglia ? { famiglia } : {}); }
  scegliModelloIA(nome: string) { return this.post<{ lavoro: Lavoro | null; stato: StatoIA }>('/api/ia/scegli', { nome }); }
  installaIA() { return this.post<Lavoro>('/api/ia/installa'); }
  avviaOllama() { return this.post<Lavoro>('/api/ia/ollama/avvia'); }
  riavviaOllama() { return this.post<Lavoro>('/api/ia/ollama/riavvia'); }
  fermaOllama() { return this.post<Lavoro>('/api/ia/ollama/ferma'); }
  scaricaModelloIA(nome: string) { return this.post<Lavoro>('/api/ia/modello', { nome }); }
  eliminaModelloIA(nome: string) {
    return this.post<{ eliminato: boolean; stato: StatoIA }>('/api/ia/modello/elimina', { nome });
  }
  provaIA(testo: string, checkpoint: string | null) { return this.post<Lavoro>('/api/ia/prova', { testo, checkpoint }); }
  ricavaTratti(progetto: string, id: string, storia: string) {
    return this.post<Lavoro>(`/api/progetti/${progetto}/personaggi/${id}/tratti`, { storia });
  }
  analizzaVignetta(progetto: string, id: string) {
    return this.post<Lavoro>(`/api/progetti/${progetto}/fumetto/vignette/${id}/analizza`);
  }
  promptVignetta(progetto: string, id: string) {
    return this.get<{ aggiornata: boolean; prompt: PromptScena | null }>(`/api/progetti/${progetto}/fumetto/vignette/${id}/prompt`);
  }
  storiaIA(progetto: string, testo: string, sostituisci: boolean) {
    return this.post<Lavoro>(`/api/progetti/${progetto}/fumetto/storia`, { testo, sostituisci });
  }

  // ------------------------------------------------------------ personaggio dal nulla
  private dp(progetto: string, id: string) { return `/api/progetti/${progetto}/personaggi/${id}/proposte`; }
  proposte(progetto: string, id: string) { return this.get<Proposta[]>(this.dp(progetto, id)); }
  generaProposte(progetto: string, id: string, conf: ConfigProposte) { return this.post<Lavoro>(this.dp(progetto, id), conf); }
  anteprimaProposte(progetto: string, id: string, conf: ConfigProposte) {
    return this.post<AnteprimaPromptProposte>(`${this.dp(progetto, id)}/anteprima`, conf);
  }
  urlProposta(progetto: string, id: string, file: string) { return `${this.dp(progetto, id)}/${encodeURIComponent(file)}`; }
  scegliProposta(progetto: string, id: string, file: string) {
    return this.post<Personaggio>(`${this.dp(progetto, id)}/${encodeURIComponent(file)}/scegli`);
  }
  scartaProposte(progetto: string, id: string) {
    return this.post<{ spostate_nel_cestino: number }>(`${this.dp(progetto, id)}/scarta`);
  }

  componenti() { return this.get<StatoComponenti>('/api/componenti'); }
  installaComponenti() { return this.post<Lavoro>('/api/componenti/installa'); }
  chiediComponenti(chiedi: boolean) { return this.post<StatoComponenti>('/api/componenti/chiedi', { chiedi }); }

  avviaComfy() { return this.post<Lavoro>('/api/comfy/avvia'); }
  fermaComfy() { return this.post<Lavoro>('/api/comfy/ferma'); }
  riavviaComfy() { return this.post<Lavoro>('/api/comfy/riavvia'); }
  impostaAvvio(dati: ImpostazioniAvvio) {
    return this.post<StatoComfy & { impostazioni: Impostazioni }>('/api/comfy/avvio', dati);
  }
  statoComfy() { return this.get<StatoComfy>('/api/comfy/stato'); }
  modelli() { return this.get<Record<string, string[]>>('/api/comfy/modelli'); }

  // controllo del sistema
  rapporto() { return this.get<Rapporto | null>('/api/diagnostica'); }
  avviaControllo(rete = true) { return this.post<Lavoro>('/api/diagnostica', {}, { rete: String(rete) }); }

  // progetti
  progetti() { return this.get<Progetto[]>('/api/progetti'); }
  progetto(id: string) { return this.get<Progetto>(`/api/progetti/${id}`); }
  creaProgetto(nome: string, descrizione = '') { return this.post<Progetto>('/api/progetti', { nome, descrizione }); }
  modificaProgetto(id: string, dati: Partial<Pick<Progetto, 'nome' | 'descrizione'>>) {
    return this.patch<Progetto>(`/api/progetti/${id}`, dati);
  }
  eliminaProgetto(id: string) { return this.del(`/api/progetti/${id}`); }

  // personaggi
  suggerisciTrigger(nome: string, progetto?: string) {
    const p: Record<string, string> = { nome };
    if (progetto) p['progetto'] = progetto;
    return this.get<{ trigger: string }>('/api/trigger/suggerisci', p);
  }
  aggiungiPersonaggio(progetto: string, dati: { nome: string; trigger?: string | null; genere: Genere; descrizione: string; storia?: string }) {
    return this.post<Personaggio>(`/api/progetti/${progetto}/personaggi`, dati);
  }
  modificaPersonaggio(progetto: string, id: string, dati: Partial<Omit<Personaggio, 'id' | 'creato' | 'riferimento'>>) {
    return this.patch<Personaggio>(`/api/progetti/${progetto}/personaggi/${id}`, dati);
  }
  eliminaPersonaggio(progetto: string, id: string) { return this.del(`/api/progetti/${progetto}/personaggi/${id}`); }
  caricaRiferimento(progetto: string, id: string, file: File) {
    const fd = new FormData();
    fd.append('file', file);
    return this.chiama(firstValueFrom(
      this.http.put<Personaggio>(`/api/progetti/${progetto}/personaggi/${id}/riferimento`, fd)));
  }
  // ------------------------------------------------------------ Step 1: workflow e dataset
  workflow(progetto: string) { return this.get<RiassuntoWorkflow[]>(`/api/progetti/${progetto}/workflows`); }
  dettaglioWorkflow(progetto: string, id: string) {
    return this.get<DettaglioWorkflow>(`/api/progetti/${progetto}/workflows/${id}`);
  }
  caricaWorkflow(progetto: string, file: File, nome = '') {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('nome', nome);
    return this.post<RiassuntoWorkflow>(`/api/progetti/${progetto}/workflows`, fd);
  }
  creaIntegrato(progetto: string, p: ParametriIntegrato) {
    return this.post<RiassuntoWorkflow>(`/api/progetti/${progetto}/workflows/integrato`, p);
  }
  modificaWorkflow(progetto: string, id: string, dati: { nome?: string; ruoli?: Ruoli }) {
    return this.patch<RiassuntoWorkflow>(`/api/progetti/${progetto}/workflows/${id}`, dati);
  }
  eliminaWorkflow(progetto: string, id: string) { return this.del(`/api/progetti/${progetto}/workflows/${id}`); }
  urlScaricaWorkflow(progetto: string, id: string) { return `/api/progetti/${progetto}/workflows/${id}/scarica`; }

  private ds(progetto: string, pers: string) { return `/api/progetti/${progetto}/personaggi/${pers}/dataset`; }
  statoDataset(progetto: string, pers: string) {
    return this.get<{ config: ConfigDataset; riepilogo: RiepilogoDataset; origine: OrigineDataset | null }>(this.ds(progetto, pers));
  }
  /** Usa per il dataset le stesse scelte delle proposte (workflow integrato con lo stesso checkpoint e LoRA). */
  comeProposte(progetto: string, pers: string) {
    return this.post<{ config: ConfigDataset; workflow: RiassuntoWorkflow; avvisi: string[]; origine: OrigineDataset }>(
      `${this.ds(progetto, pers)}/come-proposte`);
  }
  salvaConfig(progetto: string, pers: string, c: ConfigDataset) {
    return this.chiama(firstValueFrom(this.http.put<ConfigDataset>(`${this.ds(progetto, pers)}/config`, c)));
  }
  /** Anteprima dei nodi staccati: ricollegamenti, nodi staccati in automatico, problemi. */
  esclusione(progetto: string, pers: string, c: ConfigDataset) {
    return this.post<EsitoEsclusione>(`${this.ds(progetto, pers)}/esclusione`, c);
  }
  esempi(progetto: string, pers: string, c: ConfigDataset, n = 4) {
    return this.post<EsempioPrompt[]>(`${this.ds(progetto, pers)}/esempi`, c, { n: String(n) });
  }
  immaginiDataset(progetto: string, pers: string) { return this.get<ImmagineDataset[]>(`${this.ds(progetto, pers)}/immagini`); }
  urlImmagine(progetto: string, pers: string, file: string, anteprima = false) {
    return `${this.ds(progetto, pers)}/immagini/${file}${anteprima ? '?anteprima=true' : ''}`;
  }
  statoImmagine(progetto: string, pers: string, file: string, stato: StatoImmagine) {
    return this.patch<ImmagineDataset>(`${this.ds(progetto, pers)}/immagini/${file}`, { stato });
  }
  genera(progetto: string, pers: string, quantita: number, sostituisci = false) {
    return this.post<Lavoro>(`${this.ds(progetto, pers)}/genera`, { quantita, sostituisci });
  }
  selezionaAuto(progetto: string, pers: string, quante: number) {
    return this.post<Lavoro>(`${this.ds(progetto, pers)}/seleziona`, { quante });
  }
  eliminaImmagini(progetto: string, pers: string, dati: { file?: string[]; scartate?: boolean; definitivo?: boolean }) {
    return this.post<{ eliminate: number; liberati: number }>(`${this.ds(progetto, pers)}/elimina`, dati);
  }
  svuotaCestinoDataset(progetto: string, pers: string) {
    return this.post<{ immagini: number; byte: number }>(`${this.ds(progetto, pers)}/cestino/svuota`);
  }
  /** Prepara lo ZIP delle immagini (lavoro); il risultato ha nome, byte e file messi nello ZIP. */
  esportaDataset(progetto: string, pers: string, file: string[] | null) {
    return this.post<Lavoro>(`${this.ds(progetto, pers)}/esporta`, { file });
  }
  /** Scarica lo ZIP nel browser con l'avanzamento; finisce solo quando è arrivato tutto. */
  scaricaEsportazione(progetto: string, pers: string, nome: string, avanzamento: (fatto: number, totale: number) => void): Promise<Blob> {
    return new Promise((ok, ko) => {
      this.http.get(`${this.ds(progetto, pers)}/esportazioni/${encodeURIComponent(nome)}`,
        { responseType: 'blob', observe: 'events', reportProgress: true }).subscribe({
        next: (e) => {
          if (e.type === HttpEventType.DownloadProgress) avanzamento(e.loaded, e.total ?? 0);
          else if (e.type === HttpEventType.Response) {
            if (e.body) ok(e.body);
            else ko(new Error('Download vuoto'));
          }
        },
        error: (e) => ko(new Error(messaggioErrore(e))),
      });
    });
  }
  // ------------------------------------------------------------ Step 2: didascalie
  private dd(progetto: string, pers: string) { return `/api/progetti/${progetto}/personaggi/${pers}/didascalie`; }
  statoDidascalie(progetto: string, pers: string) { return this.get<StatoDidascalie>(this.dd(progetto, pers)); }
  salvaConfigDidascalie(progetto: string, pers: string, c: ConfigDidascalie) {
    return this.chiama(firstValueFrom(this.http.put<StatoDidascalie>(`${this.dd(progetto, pers)}/config`, c)));
  }
  scriviDidascalia(progetto: string, pers: string, file: string, testo: string) {
    return this.chiama(firstValueFrom(this.http.put(`${this.dd(progetto, pers)}/immagini/${file}`, { testo })));
  }
  ripristinaDidascalia(progetto: string, pers: string, file: string) {
    return this.del(`${this.dd(progetto, pers)}/immagini/${file}`);
  }
  analizzaTag(progetto: string, pers: string, tutte = false) {
    return this.post<Lavoro>(`${this.dd(progetto, pers)}/analizza`, { tutte });
  }
  urlZipDataset(progetto: string, pers: string) { return `${this.dd(progetto, pers)}/zip`; }

  // ------------------------------------------------------------ Step 3: addestramento
  kohya(ricontrolla = false) { return this.get<StatoKohya>('/api/kohya', { ricontrolla: String(ricontrolla) }); }
  installaKohya(reinstalla = false) { return this.post<Lavoro>('/api/kohya/installa', { reinstalla }); }
  private da(progetto: string, pers: string) { return `/api/progetti/${progetto}/personaggi/${pers}/addestramento`; }
  addestramento(progetto: string, pers: string) { return this.get<RiassuntoAddestramento>(this.da(progetto, pers)); }
  salvaConfigAddestramento(progetto: string, pers: string, c: ConfigAddestramento) {
    return this.chiama(firstValueFrom(this.http.put<RiassuntoAddestramento>(`${this.da(progetto, pers)}/config`, c)));
  }
  applicaPreset(progetto: string, pers: string, preset: Preset) {
    return this.post<RiassuntoAddestramento>(`${this.da(progetto, pers)}/preset`, { preset });
  }
  salvaPromptTest(progetto: string, pers: string, prompt: string[]) {
    return this.chiama(firstValueFrom(this.http.put<StatoAddestramento>(`${this.da(progetto, pers)}/prompt-test`, { prompt })));
  }
  avviaAddestramento(progetto: string, pers: string) { return this.post<Lavoro>(`${this.da(progetto, pers)}/avvia`); }
  provaEpoche(progetto: string, pers: string, epoche: number[] | null) {
    return this.post<Lavoro>(`${this.da(progetto, pers)}/prova`, { epoche });
  }
  scegliEpoca(progetto: string, pers: string, epoca: number) {
    return this.post<StatoAddestramento>(`${this.da(progetto, pers)}/scegli`, { epoca });
  }
  usaLoraEsistente(progetto: string, pers: string, lora: string | null) {
    return this.post<StatoAddestramento>(`${this.da(progetto, pers)}/esistente`, { lora });
  }
  urlTest(progetto: string, pers: string, file: string) { return `${this.da(progetto, pers)}/test/${file}`; }

  // ------------------------------------------------------------ Step 4: fumetto
  private df(progetto: string) { return `/api/progetti/${progetto}/fumetto`; }
  fumetto(progetto: string) { return this.get<StatoFumetto>(this.df(progetto)); }
  salvaFumetto(progetto: string, f: Fumetto) {
    return this.chiama(firstValueFrom(this.http.put<{ ok: boolean }>(this.df(progetto), f)));
  }
  importaStoria(progetto: string, testo: string, sostituisci = false) {
    return this.post<StatoFumetto>(`${this.df(progetto)}/importa`, { testo, sostituisci });
  }
  generaVignette(progetto: string, vignette: string[] | null, stessoSeme = false) {
    return this.post<Lavoro>(`${this.df(progetto)}/genera`, { vignette, stesso_seme: stessoSeme });
  }
  scegliVersione(progetto: string, vid: string, indice: number) {
    return this.chiama(firstValueFrom(this.http.put<ImmaginiVignetta>(`${this.df(progetto)}/vignette/${vid}/scelta`, { indice })));
  }
  urlVignetta(progetto: string, file: string) { return `${this.df(progetto)}/immagini/${file}`; }
  urlAnteprimaPagina(progetto: string, indice: number, larghezza = 900) {
    return `${this.df(progetto)}/pagine/${indice}/anteprima?larghezza=${larghezza}`;
  }
  urlEsporta(progetto: string, formato: 'pdf' | 'zip') { return `${this.df(progetto)}/esporta?formato=${formato}`; }

  specNodi(classi: string[]) {
    return this.get<Record<string, SpecNodo>>('/api/comfy/nodi', { classi: classi.join(',') });
  }

  urlRiferimento(progetto: string, p: Personaggio): string | null {
    return p.riferimento ? `/api/progetti/${progetto}/personaggi/${p.id}/riferimento?v=${p.creato}-${encodeURIComponent(p.riferimento)}` : null;
  }
}

export function messaggioErrore(e: unknown): string {
  if (e instanceof HttpErrorResponse) {
    if (e.status === 0) return 'Il programma non risponde: controlla che Comic Studio sia ancora avviato.';
    const d = e.error?.detail;
    if (typeof d === 'string') return d;
    if (Array.isArray(d) && d.length) return d.map((x: { msg?: string }) => x.msg ?? JSON.stringify(x)).join('; ');
    return `Errore ${e.status}: ${e.statusText}`;
  }
  return e instanceof Error ? e.message : String(e);
}

/** Impostazioni dell'IA locale che si possono cambiare (quelle assenti restano come sono). */
export interface ImpostazioniIA {
  tipo?: string;
  url?: string;
  modello?: string;
  chiave?: string;
  libera_gpu?: boolean;
  avvio_automatico?: boolean;
}
