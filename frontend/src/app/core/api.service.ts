import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { Genere, Lavoro, Personaggio, Progetto, Rapporto, RigaLog, Sistema, StatoComfy } from './modelli';

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
