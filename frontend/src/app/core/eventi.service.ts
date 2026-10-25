import { Injectable, computed, inject, signal } from '@angular/core';
import { ApiService } from './api.service';
import { Evento, EventoDataset, Installazione, Lavoro, Rapporto, RigaLog, Sistema, StatoComfy } from './modelli';

const MAX_LOG = 3000;

/**
 * Stato in tempo reale dell'applicazione, alimentato dal WebSocket /api/eventi:
 * log della console, lavori con il loro avanzamento, stato di ComfyUI e ultimo controllo del sistema.
 */
@Injectable({ providedIn: 'root' })
export class EventiService {
  private api = inject(ApiService);
  private ws?: WebSocket;
  private tentativi = 0;

  readonly collegato = signal(false);
  readonly log = signal<RigaLog[]>([]);
  readonly lavori = signal<Record<string, Lavoro>>({});
  readonly comfy = signal<StatoComfy | null>(null);
  readonly installazioni = signal<Installazione[]>([]);
  readonly rapporto = signal<Rapporto | null>(null);
  readonly sistema = signal<Sistema | null>(null);
  /** Ultimo evento del dataset (nuova immagine, cambio di stato, elenco da ricaricare). */
  readonly dataset = signal<EventoDataset | null>(null, { equal: () => false });

  /** Lavori in coda o in corso, il più recente per primo. */
  readonly attivi = computed(() =>
    Object.values(this.lavori())
      .filter((l) => l.stato === 'in_coda' || l.stato === 'in_corso')
      .sort((a, b) => b.creato - a.creato),
  );
  readonly errori = computed(() => this.log().filter((r) => r.livello === 'errore').length);

  async avvia() {
    await this.ricarica();
    this.collega();
  }

  async ricarica() {
    try {
      const [s, log, lavori] = await Promise.all([this.api.sistema(), this.api.log(), this.api.lavori()]);
      this.sistema.set(s);
      this.comfy.set(s.comfy);
      this.installazioni.set(s.installazioni);
      this.rapporto.set(s.rapporto);
      this.log.set(log);
      this.lavori.set(Object.fromEntries(lavori.map((l) => [l.id, l])));
    } catch {
      /* il backend non è ancora pronto: ci riprova il WebSocket */
    }
  }

  private collega() {
    const protocollo = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${protocollo}://${location.host}/api/eventi`);
    this.ws = ws;
    ws.onopen = () => {
      const eraCaduto = this.tentativi > 0;
      this.tentativi = 0;
      this.collegato.set(true);
      if (eraCaduto) void this.ricarica();
    };
    ws.onmessage = (m) => this.ricevi(JSON.parse(m.data) as Evento);
    ws.onclose = () => {
      this.collegato.set(false);
      const attesa = Math.min(10000, 500 * 2 ** this.tentativi++);
      setTimeout(() => this.collega(), attesa);
    };
  }

  private ricevi(e: Evento) {
    switch (e.tipo) {
      case 'log':
        this.log.update((l) => (l.length >= MAX_LOG ? [...l.slice(-MAX_LOG + 1), e] : [...l, e]));
        break;
      case 'avanzamento':
        this.lavori.update((l) => {
          const x = l[e.lavoro];
          return x ? { ...l, [e.lavoro]: { ...x, progresso: e.progresso, testo: e.testo } } : l;
        });
        break;
      case 'lavoro':
        this.lavori.update((l) => ({ ...l, [e.lavoro]: e.dati }));
        break;
      case 'comfy':
        this.comfy.set(e.dati);
        break;
      case 'installazioni':
        this.installazioni.set(e.dati);
        break;
      case 'diagnostica':
        this.rapporto.set(e.dati);
        break;
      case 'dataset':
        this.dataset.set(e);
        break;
      case 'benvenuto':
        this.comfy.set(e.comfy);
        this.lavori.update((l) => ({ ...l, ...Object.fromEntries(e.lavori.map((x) => [x.id, x])) }));
        break;
    }
  }

  /** Svuota la console solo nella vista (il backend conserva lo storico). */
  pulisciLog() {
    this.log.set([]);
  }

  /** Attende la fine di un lavoro e lo restituisce. */
  attendi(id: string): Promise<Lavoro> {
    return new Promise((ok) => {
      const controlla = () => {
        const l = this.lavori()[id];
        if (l && !['in_coda', 'in_corso'].includes(l.stato)) ok(l);
        else setTimeout(controlla, 250);
      };
      controlla();
    });
  }
}
