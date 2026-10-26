import { Component, computed, effect, inject, input, model, output, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatMenuModule } from '@angular/material/menu';
import { MatSelectModule } from '@angular/material/select';
import { MatSliderModule } from '@angular/material/slider';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ApiService } from '../../core/api.service';
import { AvvisiService } from '../../core/avvisi.service';
import { EventiService } from '../../core/eventi.service';
import {
  ConfigDataset, DettaglioWorkflow, EsitoEsclusione, NodoAnalisi, ParametriIntegrato, RUOLI, RiassuntoWorkflow, Ruoli, Ruolo, SpecIngresso, SpecNodo,
} from '../../core/modelli';

interface Campo {
  nodo: string;
  nome: string;
  originale: unknown;
  valore: unknown;
  tipo: 'numero' | 'testo' | 'scelta' | 'si_no';
  opzioni: string[];
  modificato: boolean;
}

/** Campi gestiti dal programma: non si modificano a mano. */
const AUTOMATICI: Partial<Record<Ruolo, string[]>> = {
  riferimento: ['image'],
  positivo: ['text', 'text_g', 'text_l'],
  negativo: ['text', 'text_g', 'text_l'],
  seme: ['seed', 'noise_seed'],
  latente: ['width', 'height', 'batch_size'],
  salva: ['filename_prefix'],
};

@Component({
  selector: 'app-sezione-workflow',
  imports: [FormsModule, MatButtonModule, MatButtonToggleModule, MatFormFieldModule, MatIconModule, MatInputModule, MatMenuModule, MatSelectModule,
    MatSliderModule, MatTooltipModule],
  templateUrl: './sezione-workflow.html',
  styleUrl: './sezione-workflow.scss',
})
export class SezioneWorkflow {
  readonly progetto = input.required<string>();
  /** id del personaggio (per l'anteprima dei nodi staccati) */
  readonly personaggio = input<string | null>(null);
  readonly libreria = input.required<RiassuntoWorkflow[]>();
  readonly config = model.required<ConfigDataset | null>();
  readonly libreriaCambiata = output<void>();

  private api = inject(ApiService);
  private avvisi = inject(AvvisiService);
  private eventi = inject(EventiService);
  protected ruoliElenco = RUOLI;

  protected dettaglio = signal<DettaglioWorkflow | null>(null);
  protected spec = signal<Record<string, SpecNodo>>({});
  protected caricando = signal(false);
  protected integratoAperto = signal(false);
  protected modelli = signal<Record<string, string[]>>({});
  protected filtroNodi = signal('');
  protected parametriAperti = signal(false);
  protected integrato = signal<ParametriIntegrato>({
    checkpoint: '', ipadapter: '', clip_vision: '', lora_stile: null, forza_stile: 0.6, peso_ipadapter: 0.7,
    fine_ipadapter: 0.8, passi: 30, cfg: 6.5, sampler: 'euler_ancestral', scheduler: 'karras',
  });

  /** il workflow parte dall'immagine di riferimento (img2img): senza intervento tutte le pose sarebbero uguali */
  protected img2img = computed(() => this.dettaglio()?.analisi.img2img ?? null);
  protected composizioneLibera = computed(() => !!this.img2img() && (this.config()?.composizione ?? 'libera') === 'libera');
  /** da dove viene l'aspetto del personaggio quando la composizione è libera */
  protected aspetto = computed(() => {
    const a = this.dettaglio()?.analisi;
    if (!a) return '';
    const parti = [...new Set(a.guide ?? [])].concat(a.lora.map((l) => l.replace(/\.safetensors$/i, '')));
    return parti.join(', ');
  });
  protected scelto = computed(() => this.libreria().find((w) => w.id === this.config()?.workflow) ?? null);
  protected ruoli = computed<Ruoli | null>(() => {
    const w = this.scelto();
    return w ? ({ ...w.ruoli, ...(this.config()?.ruoli ?? {}) } as Ruoli) : null;
  });

  /** Nodi selezionabili per ogni ruolo, con un'etichetta leggibile. */
  protected opzioniRuolo = computed(() => {
    const d = this.dettaglio();
    const out: Record<string, { id: string; etichetta: string }[]> = {};
    if (!d) return out;
    const titolo = (id: string) => {
      const n = d.workflow[id];
      return `#${id} · ${n?._meta?.title || n?.class_type}${n?._meta?.title && n._meta.title !== n.class_type ? ` (${n.class_type})` : ''}`;
    };
    for (const r of RUOLI) {
      const candidati = d.analisi.candidati[r.chiave] ?? [];
      const attuale = this.ruoli()?.[r.chiave];
      const ids = attuale && !candidati.includes(attuale) ? [...candidati, attuale] : candidati;
      out[r.chiave] = ids.map((id) => ({ id, etichetta: titolo(id) }));
    }
    return out;
  });

  protected campi = computed<{ nodo: NodoAnalisi; campi: Campo[]; staccato: boolean; automatico: string | null }[]>(() => {
    const d = this.dettaglio();
    const cfg = this.config();
    if (!d || !cfg) return [];
    const ruoli = this.ruoli() ?? ({} as Ruoli);
    const esclusi = new Map<string, Set<string>>();
    for (const [r, campi] of Object.entries(AUTOMATICI)) {
      const id = ruoli[r as Ruolo];
      if (id) esclusi.set(id, new Set([...(esclusi.get(id) ?? []), ...campi]));
    }
    const filtro = this.filtroNodi().trim().toLowerCase();
    const spec = this.spec();
    return d.analisi.nodi
      .filter((n) => !filtro || `${n.id} ${n.titolo} ${n.classe}`.toLowerCase().includes(filtro))
      .map((n) => {
        const s = spec[n.classe];
        const campi = Object.entries(n.valori)
          .filter(([nome]) => !esclusi.get(n.id)?.has(nome))
          .map(([nome, originale]): Campo => {
            const sp = s ? (s.input.required?.[nome] ?? s.input.optional?.[nome]) : undefined;
            const mod = cfg.modifiche[n.id]?.[nome];
            return {
              nodo: n.id, nome, originale, valore: mod !== undefined ? mod : originale, modificato: mod !== undefined,
              ...tipoCampo(originale, sp),
            };
          });
        return { nodo: n, campi, staccato: this.disattivati().has(n.id), automatico: this.automatici().get(n.id) ?? null };
      });
  });

  protected numeroModifiche = computed(() =>
    Object.values(this.config()?.modifiche ?? {}).reduce((s, m) => s + Object.keys(m).length, 0));

  /** nodi staccati dall'utente e cosa ne segue (ricollegamenti, nodi staccati in automatico, problemi) */
  protected disattivati = computed(() => new Set(this.config()?.disattivati ?? []));
  protected esito = signal<EsitoEsclusione | null>(null);
  protected automatici = computed(() => new Map((this.esito()?.automatici ?? []).map((a) => [a.nodo, a.perche])));
  private timerEsito?: ReturnType<typeof setTimeout>;

  constructor() {
    effect(() => {
      const w = this.scelto();
      untracked(() => void this.caricaDettaglio(w?.id ?? null));
    });
    // anteprima dei nodi staccati a ogni cambio della configurazione che conta
    effect(() => {
      const c = this.config();
      const pers = this.personaggio();
      const chiave = c ? JSON.stringify([c.workflow, c.disattivati, c.ruoli, c.composizione, c.modifiche]) : '';
      clearTimeout(this.timerEsito);
      if (!c?.workflow || !pers || !c.disattivati?.length) {
        this.esito.set(null);
        return;
      }
      this.timerEsito = setTimeout(() => void this.aggiornaEsito(c, pers, chiave), 250);
    });
  }

  private ultimaChiave = '';
  private async aggiornaEsito(c: ConfigDataset, pers: string, chiave: string) {
    this.ultimaChiave = chiave;
    try {
      const e = await this.api.esclusione(this.progetto(), pers, c);
      if (this.ultimaChiave === chiave) this.esito.set(e);
    } catch {
      this.esito.set(null);
    }
  }

  /** Stacca o riattacca un nodo; i collegamenti li rifà Comic Studio al momento della generazione. */
  protected stacca(id: string) {
    this.config.update((c) => {
      if (!c) return c;
      const s = new Set(c.disattivati ?? []);
      if (s.has(id)) s.delete(id);
      else s.add(id);
      return { ...c, disattivati: [...s] };
    });
  }

  protected riattaccaTutti() {
    this.config.update((c) => (c ? { ...c, disattivati: [] } : c));
  }

  private async caricaDettaglio(id: string | null) {
    this.dettaglio.set(null);
    if (!id) return;
    try {
      const d = await this.api.dettaglioWorkflow(this.progetto(), id);
      if (this.scelto()?.id !== id) return;
      this.dettaglio.set(d);
      if (this.eventi.comfy()?.connesso) {
        const classi = [...new Set(d.analisi.nodi.map((n) => n.classe))];
        this.spec.set(await this.api.specNodi(classi).catch(() => ({})));
      }
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected scegli(id: string | null) {
    this.config.update((c) => (c ? { ...c, workflow: id, ruoli: null, modifiche: {} } : c));
  }

  protected async caricaFile(ev: Event) {
    const inp = ev.target as HTMLInputElement;
    const file = inp.files?.[0];
    inp.value = '';
    if (!file) return;
    this.caricando.set(true);
    try {
      const w = await this.api.caricaWorkflow(this.progetto(), file);
      this.libreriaCambiata.emit();
      this.scegli(w.id);
      this.avvisi.ok(`Workflow «${w.nome}» caricato`);
    } catch (e) {
      this.avvisi.errore(e);
    } finally {
      this.caricando.set(false);
    }
  }

  protected async apriIntegrato() {
    this.integratoAperto.set(true);
    try {
      const m = await this.api.modelli();
      this.modelli.set(m);
      // il primo file che corrisponde alla preferenza più alta
      const scegliPrimo = (l: string[] | undefined, preferenze: RegExp[]) => {
        for (const re of preferenze) {
          const trovato = l?.find((x) => re.test(x));
          if (trovato) return trovato;
        }
        return l?.[0] ?? '';
      };
      this.integrato.update((p) => ({
        ...p,
        checkpoint: p.checkpoint || scegliPrimo(m['checkpoints'], [/illustrious/i, /noob/i, /pony/i, /xl/i]),
        ipadapter: p.ipadapter || scegliPrimo(m['ipadapter'], [/plus.*sdxl.*vit-?h/i, /sdxl.*vit-?h/i, /sdxl|xl/i]),
        clip_vision: p.clip_vision || scegliPrimo(m['clip_vision'], [/vit-?h/i, /laion/i]),
      }));
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected impostaIntegrato<K extends keyof ParametriIntegrato>(k: K, v: ParametriIntegrato[K]) {
    this.integrato.update((p) => ({ ...p, [k]: v }));
  }

  protected async creaIntegrato() {
    try {
      const w = await this.api.creaIntegrato(this.progetto(), this.integrato());
      this.libreriaCambiata.emit();
      this.scegli(w.id);
      this.integratoAperto.set(false);
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected impostaRuolo(r: Ruolo, id: string | null) {
    this.config.update((c) => (c ? { ...c, ruoli: { ...(c.ruoli ?? {}), [r]: id } } : c));
  }

  protected impostaComposizione(c: 'libera' | 'riferimento') {
    this.config.update((cfg) => (cfg ? { ...cfg, composizione: c } : cfg));
  }

  protected ripristinaRuoli() {
    this.config.update((c) => (c ? { ...c, ruoli: null } : c));
  }

  protected impostaCampo(c: Campo, valore: unknown) {
    const v = c.tipo === 'numero' ? Number(valore) : valore;
    this.config.update((cfg) => {
      if (!cfg) return cfg;
      const modifiche = structuredClone(cfg.modifiche);
      const nodo = { ...(modifiche[c.nodo] ?? {}) };
      if (v === c.originale || (c.tipo === 'numero' && Number.isNaN(v))) delete nodo[c.nome];
      else nodo[c.nome] = v;
      if (Object.keys(nodo).length) modifiche[c.nodo] = nodo;
      else delete modifiche[c.nodo];
      return { ...cfg, modifiche };
    });
  }

  protected azzeraModifiche() {
    this.config.update((c) => (c ? { ...c, modifiche: {} } : c));
  }

  protected async rinomina() {
    const w = this.scelto();
    if (!w) return;
    const nome = prompt('Nuovo nome del workflow', w.nome);
    if (!nome?.trim()) return;
    try {
      await this.api.modificaWorkflow(this.progetto(), w.id, { nome });
      this.libreriaCambiata.emit();
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected async elimina() {
    const w = this.scelto();
    if (!w || !confirm(`Eliminare il workflow «${w.nome}» dalla libreria del progetto?`)) return;
    try {
      await this.api.eliminaWorkflow(this.progetto(), w.id);
      this.scegli(null);
      this.libreriaCambiata.emit();
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected urlScarica() {
    const w = this.scelto();
    return w ? this.api.urlScaricaWorkflow(this.progetto(), w.id) : null;
  }

  protected testo(v: unknown) {
    return typeof v === 'string' ? v : JSON.stringify(v);
  }
}

function tipoCampo(originale: unknown, spec: SpecIngresso | undefined): Pick<Campo, 'tipo' | 'opzioni'> {
  const tipo = spec?.[0];
  if (Array.isArray(tipo)) return { tipo: 'scelta', opzioni: tipo.map(String) };
  if (tipo === 'COMBO') {
    const op = (spec?.[1]?.['options'] as unknown[]) ?? [];
    return { tipo: 'scelta', opzioni: op.map(String) };
  }
  if (tipo === 'BOOLEAN' || typeof originale === 'boolean') return { tipo: 'si_no', opzioni: [] };
  if (tipo === 'INT' || tipo === 'FLOAT' || typeof originale === 'number') return { tipo: 'numero', opzioni: [] };
  return { tipo: 'testo', opzioni: [] };
}
