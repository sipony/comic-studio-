import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import {
  ConfigAddestramento, ConfigDataset, ConfigDidascalie, DettaglioWorkflow, Impostazioni, ImpostazioniAvvio, Preset, RiassuntoAddestramento,
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

  // ComfyUI
  cercaComfy() { return this.post<Lavoro>('/api/comfy/cerca'); }
  usaComfy(url: string | null, cartella: string | null) {
    return this.post<StatoComfy>('/api/comfy/usa', { url, cartella });
  }
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
  aggiungiPersonaggio(progetto: string, dati: { nome: string; trigger?: string | null; genere: Genere; descrizione: string }) {
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
    return this.get<{ config: ConfigDataset; riepilogo: RiepilogoDataset }>(this.ds(progetto, pers));
  }
  salvaConfig(progetto: string, pers: string, c: ConfigDataset) {
    return this.chiama(firstValueFrom(this.http.put<ConfigDataset>(`${this.ds(progetto, pers)}/config`, c)));
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
  eliminaImmagini(progetto: string, pers: string, dati: { file?: string[]; scartate?: boolean }) {
    return this.post<{ eliminate: number }>(`${this.ds(progetto, pers)}/elimina`, dati);
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
