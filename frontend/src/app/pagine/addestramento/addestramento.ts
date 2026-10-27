import { DecimalPipe } from '@angular/common';
import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ApiService } from '../../core/api.service';
import { AvvisiService } from '../../core/avvisi.service';
import { EventiService } from '../../core/eventi.service';
import { ConfigAddestramento, Preset, RiassuntoAddestramento, StatoKohya, VersioneLora } from '../../core/modelli';
import { ProgettoService } from '../../core/progetto.service';
import { SceltaPersonaggio } from '../../shell/scelta-personaggio';
import { GraficoLoss } from './grafico-loss';

const PRESET: { valore: Preset; etichetta: string; descrizione: string }[] = [
  { valore: '8gb', etichetta: '8 GB sicuro', descrizione: 'fp8, rank 16, Adafactor, solo UNet' },
  { valore: 'equilibrato', etichetta: 'Equilibrato', descrizione: '12 GB: rank 32, AdamW 8bit' },
  { valore: 'qualita', etichetta: 'Qualità', descrizione: '16 GB+: rank 32, anche il text encoder' },
  { valore: 'personalizzato', etichetta: 'Personalizzato', descrizione: 'i tuoi valori' },
];

/** Campi che, se cambiati, rendono il preset "personalizzato". */
const DEL_PRESET: (keyof ConfigAddestramento)[] = ['rank', 'alpha', 'learning_rate', 'ottimizzatore', 'batch', 'fp8',
  'gradient_checkpointing', 'allena_text_encoder', 'learning_rate_te', 'risoluzione'];

@Component({
  selector: 'app-addestramento',
  imports: [DecimalPipe, FormsModule, MatButtonModule, MatButtonToggleModule, MatFormFieldModule, MatIconModule, MatInputModule,
    MatProgressBarModule, MatSelectModule, MatSlideToggleModule, MatTooltipModule, SceltaPersonaggio, GraficoLoss],
  templateUrl: './addestramento.html',
  styleUrl: './addestramento.scss',
})
export class AddestramentoPage {
  protected progetti = inject(ProgettoService);
  private api = inject(ApiService);
  private avvisi = inject(AvvisiService);
  protected eventi = inject(EventiService);
  protected preset = PRESET;

  protected progetto = computed(() => this.progetti.corrente()!);
  protected personaggi = computed(() => this.progetto().personaggi);
  protected sceltoId = signal<string | null>(null);
  protected personaggio = computed(() => this.personaggi().find((p) => p.id === this.sceltoId()) ?? null);

  protected kohya = signal<StatoKohya | null>(null);
  protected dati = signal<RiassuntoAddestramento | null>(null);
  protected config = signal<ConfigAddestramento | null>(null);
  protected checkpoint = signal<string[]>([]);
  protected lora = signal<string[]>([]);
  protected avanzate = signal(false);
  protected loss = signal<[number, number][]>([]);
  protected dal_vivo = signal<{ passo: number; totale: number; epoca: number; epoche: number; velocita: string; rimanente: string } | null>(null);
  protected daProvare = signal<Set<number>>(new Set());
  protected promptTest = signal('');

  protected lavoroKohya = computed(() => this.eventi.attivi().find((l) => l.tipo === 'kohya_installa') ?? null);
  protected lavoro = computed(() => {
    const p = this.personaggio();
    return p ? this.eventi.attivi().find((l) => l.tipo.startsWith('addestramento') && l.titolo.endsWith(p.nome)) ?? null : null;
  });
  protected inAddestramento = computed(() => this.lavoro()?.tipo === 'addestramento');
  protected altroInCorso = computed(() =>
    this.eventi.attivi().some((l) => (l.tipo === 'addestramento' || l.tipo.startsWith('dataset_genera')) && l !== this.lavoro()));

  protected problemi = computed(() => {
    const d = this.dati();
    const out: string[] = [];
    if (!this.kohya()?.installato) out.push('Installa prima kohya sd-scripts (qui sopra).');
    if (d && d.immagini < 5) out.push(`Il dataset ha ${d.immagini} immagini: ne servono almeno 5 (meglio 20-40), vedi Step 1.`);
    if (!this.config()?.checkpoint) out.push('Scegli il checkpoint su cui addestrare.');
    return out;
  });

  protected colonneTest = computed(() => {
    const t = this.dati()?.stato.test ?? {};
    const voci = Object.entries(t).map(([e, v]) => ({ epoca: +e, ...v })).sort((a, b) => a.epoca - b.epoca);
    const punti = voci.map((v) => v.punteggio).filter((x): x is number => x !== null);
    const migliore = punti.length ? Math.max(...punti) : null;
    const consigliata = migliore === null ? null : voci.find((v) => v.punteggio !== null && v.punteggio >= migliore - 0.01)?.epoca ?? null;
    return { voci, consigliata, righe: Math.max(0, ...voci.map((v) => v.immagini.length)) };
  });

  private timer?: ReturnType<typeof setTimeout>;
  private inviato = '';

  constructor() {
    void this.caricaKohya();
    void this.api.modelli().then((m) => {
      this.checkpoint.set(m['checkpoints'] ?? []);
      this.lora.set(m['loras'] ?? []);
    }).catch(() => undefined);
    effect(() => {
      if (this.sceltoId()) untracked(() => void this.carica());
    });
    effect(() => {
      this.eventi.kohya();
      untracked(() => void this.caricaKohya(true));
    });
    effect(() => {
      const e = this.eventi.addestramento();
      if (!e || e.progetto !== this.progetto().id || e.personaggio !== untracked(this.sceltoId)) return;
      untracked(() => {
        if (e.punto) {
          this.loss.update((l) => [...l, e.punto!]);
          this.dal_vivo.set({ passo: e.passo ?? 0, totale: e.totale ?? 0, epoca: e.epoca ?? 0, epoche: e.epoche ?? 0,
            velocita: e.velocita ?? '', rimanente: e.rimanente ?? '' });
        }
        if (e.epoche_cambiate || e.test) void this.carica();
      });
    });
  }

  private async caricaKohya(ricontrolla = false) {
    try {
      this.kohya.set(await this.api.kohya(ricontrolla));
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected async carica() {
    const id = this.sceltoId();
    if (!id) return;
    try {
      const d = await this.api.addestramento(this.progetto().id, id);
      if (id !== this.sceltoId()) return;
      this.imposta(d);
      if (!d.config.checkpoint && d.checkpoint_suggerito) this.cambia('checkpoint', d.checkpoint_suggerito);
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  private imposta(d: RiassuntoAddestramento) {
    this.dati.set(d);
    this.config.set(d.config);
    this.inviato = JSON.stringify(d.config);
    if (!this.inAddestramento()) this.loss.set(d.loss);
    this.promptTest.set(d.stato.prompt_test.join('\n'));
    const ep = d.epoche.map((e) => e.epoca);
    const suggerite = ep.length <= 4 ? ep : [0.4, 0.6, 0.8, 1].map((f) => ep[Math.round((ep.length - 1) * f)]);
    this.daProvare.set(new Set(suggerite));
  }

  protected cambia<K extends keyof ConfigAddestramento>(k: K, v: ConfigAddestramento[K]) {
    const c = this.config();
    if (!c) return;
    const nuovo = { ...c, [k]: v };
    if (DEL_PRESET.includes(k) && c[k] !== v) nuovo.preset = 'personalizzato';
    this.config.set(nuovo);
    clearTimeout(this.timer);
    this.timer = setTimeout(() => void this.salva(), 500);
  }

  protected numero<K extends keyof ConfigAddestramento>(k: K, testo: string) {
    const v = Number(String(testo).replace(',', '.'));
    if (Number.isFinite(v)) this.cambia(k, v as ConfigAddestramento[K]);
  }

  private async salva(): Promise<boolean> {
    const c = this.config();
    const id = this.sceltoId();
    if (!c || !id) return false;
    const json = JSON.stringify(c);
    if (json === this.inviato) return true;
    try {
      this.inviato = json;
      const d = await this.api.salvaConfigAddestramento(this.progetto().id, id, c);
      if (JSON.stringify(this.config()) === json) this.dati.set(d);
      return true;
    } catch (e) {
      this.inviato = '';
      this.avvisi.errore(e);
      return false;
    }
  }

  protected async scegliPreset(p: Preset) {
    if (p === 'personalizzato') return this.cambia('preset', p);
    clearTimeout(this.timer);
    await this.salva();
    try {
      this.imposta(await this.api.applicaPreset(this.progetto().id, this.sceltoId()!, p));
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected async installa(reinstalla = false) {
    if (reinstalla && !confirm('Reinstallare l’ambiente di kohya? Scarica di nuovo PyTorch e le librerie (circa 3 GB).')) return;
    try {
      await this.api.installaKohya(reinstalla);
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected async avvia() {
    clearTimeout(this.timer);
    if (!(await this.salva())) return;
    const d = this.dati();
    if (d?.epoche.length && !confirm('Le epoche dell’addestramento precedente verranno spostate nel cestino. Continuare?')) return;
    try {
      this.loss.set([]);
      this.dal_vivo.set(null);
      await this.api.avviaAddestramento(this.progetto().id, this.sceltoId()!);
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected async ferma(id: string) {
    await this.api.annulla(id).catch((e) => this.avvisi.errore(e));
  }

  protected alternaProva(e: number) {
    this.daProvare.update((s) => {
      const n = new Set(s);
      if (n.has(e)) n.delete(e);
      else n.add(e);
      return n;
    });
  }

  protected async prova() {
    const righe = this.promptTest().split('\n').map((x) => x.trim()).filter(Boolean);
    try {
      if (righe.length) await this.api.salvaPromptTest(this.progetto().id, this.sceltoId()!, righe);
      await this.api.provaEpoche(this.progetto().id, this.sceltoId()!, [...this.daProvare()].sort((a, b) => a - b));
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected async usaVersione(v: VersioneLora) {
    try {
      this.dati.set(await this.api.usaVersioneLora(this.progetto().id, this.sceltoId()!, v.versione));
      this.avvisi.ok(`LoRA in uso: versione ${v.versione}`);
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected async eliminaVersione(v: VersioneLora) {
    if (!confirm(`Spostare nel cestino la versione ${v.versione} (${v.nome_file})?`)) return;
    try {
      this.dati.set(await this.api.eliminaVersioneLora(this.progetto().id, this.sceltoId()!, v.versione));
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected data(t: number | null | undefined) {
    return t ? new Date(t * 1000).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'short' }) : '—';
  }

  protected parametri(p: Record<string, unknown>) {
    if (!p || !Object.keys(p).length) return '';
    const lr = typeof p['learning_rate'] === 'number' ? (p['learning_rate'] as number).toExponential(0) : p['learning_rate'];
    return [p['preset'], p['rank'] != null ? `rank ${p['rank']}` : '', lr ? `lr ${lr}` : '', p['immagini'] != null ? `${p['immagini']} immagini` : '',
      p['passi'] != null ? `${p['passi']} passi` : ''].filter(Boolean).join(' · ');
  }

  protected async usa(epoca: number) {
    try {
      const s = await this.api.scegliEpoca(this.progetto().id, this.sceltoId()!, epoca);
      this.dati.update((d) => (d ? { ...d, stato: s } : d));
      await this.carica();
      this.avvisi.ok(`LoRA pronto per il fumetto: ${s.lora_finale}`);
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected async usaEsistente(lora: string | null) {
    try {
      const s = await this.api.usaLoraEsistente(this.progetto().id, this.sceltoId()!, lora);
      this.dati.update((d) => (d ? { ...d, stato: s } : d));
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected urlTest(file: string) {
    return this.api.urlTest(this.progetto().id, this.sceltoId()!, file) + `?v=${this.dati()?.stato.ultimo_avvio ?? 0}`;
  }

  protected mb(byte: number) {
    return Math.round(byte / 1024 / 1024);
  }

  protected durata(s: number | null | undefined) {
    if (!s) return '—';
    const m = Math.round(s / 60);
    return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
  }
}
