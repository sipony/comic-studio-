import { Component, computed, effect, inject, input, output, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ApiService } from '../../core/api.service';
import { AvvisiService } from '../../core/avvisi.service';
import { EventiService } from '../../core/eventi.service';
import { SceltaIAService } from '../../core/scelta-ia.service';
import { AnteprimaLavoro } from '../../shell/anteprima-lavoro';
import {
  AnteprimaPromptProposte, ConfigProposte, GENERI, Genere, InquadraturaProposta, NEGATIVO_PROPOSTE, NOMI_FAMIGLIA, Personaggio,
  Proposta, RicettaProposta, SAMPLER, SCHEDULER, TrattiRicavati,
} from '../../core/modelli';

@Component({
  selector: 'app-scheda-personaggio',
  imports: [AnteprimaLavoro, FormsModule, MatButtonModule, MatFormFieldModule, MatIconModule, MatInputModule, MatProgressBarModule, MatSelectModule,
    MatTooltipModule],
  templateUrl: './scheda-personaggio.html',
  styleUrl: './scheda-personaggio.scss',
})
export class SchedaPersonaggio {
  readonly progetto = input.required<string>();
  readonly personaggio = input.required<Personaggio>();
  readonly cambiato = output<Personaggio>();
  readonly eliminato = output<string>();

  private api = inject(ApiService);
  private avvisi = inject(AvvisiService);
  protected eventi = inject(EventiService);
  private sceltaIA = inject(SceltaIAService);
  protected generi = GENERI;

  protected nome = signal('');
  protected trigger = signal('');
  protected genere = signal<Genere>('1girl');
  protected descrizione = signal('');
  protected storia = signal('');
  protected adulto = signal<boolean | null>(null);
  protected ricavando = signal(false);
  protected note = signal('');

  // personaggio dal nulla
  protected proposteAperte = signal(false);
  protected proposte = signal<Proposta[]>([]);
  protected elencoCheckpoint = signal<string[]>([]);
  protected checkpoint = signal('');
  protected inquadratura = signal<InquadraturaProposta>('mezzo_busto');
  protected numero = signal(4);
  protected stile = signal('');
  protected elencoLora = signal<string[]>([]);
  protected lora = signal<string | null>(null);
  protected forzaLora = signal(0.8);
  protected extra = signal('');
  protected negativo = signal(NEGATIVO_PROPOSTE);
  protected passi = signal(28);
  protected cfg = signal(6);
  protected sampler = signal('euler_ancestral');
  protected scheduler = signal('karras');
  protected avanzate = signal(false);
  protected anteprima = signal<AnteprimaPromptProposte | null>(null);
  protected readonly samplerDisponibili = SAMPLER;
  protected readonly schedulerDisponibili = SCHEDULER;
  protected readonly negativoPredefinito = NEGATIVO_PROPOSTE;
  /** tutte le scelte delle proposte (le stesse passano poi al dataset) */
  protected scelte = computed<ConfigProposte>(() => ({
    checkpoint: this.checkpoint(), numero: this.numero(), inquadratura: this.inquadratura(), stile: this.stile().trim(),
    extra: this.extra().trim(), negativo: this.negativo().trim() || NEGATIVO_PROPOSTE, passi: this.passi(), cfg: this.cfg(),
    sampler: this.sampler(), scheduler: this.scheduler(), lora_stile: this.lora(), forza_lora: this.forzaLora(),
  }));
  protected famiglia = computed(() => NOMI_FAMIGLIA[this.anteprima()?.famiglia ?? ''] ?? this.anteprima()?.famiglia ?? '');
  private timerAnteprima: ReturnType<typeof setTimeout> | null = null;
  private precompilato = false;
  protected proposteRecenti = computed(() => [...this.proposte()].reverse());
  protected haScelta = computed(() => this.proposte().some((p) => p.scelta));
  protected lavoroProposte = computed(() =>
    this.eventi.attivi().find((l) => l.tipo === 'proposte' && l.progetto === this.progetto() &&
      l.titolo.endsWith(this.personaggio().nome)) ?? null);
  protected trascina = signal(false);
  protected occupato = signal(false);

  protected immagine = computed(() => this.api.urlRiferimento(this.progetto(), this.personaggio()));
  protected modificato = computed(() => {
    const p = this.personaggio();
    return this.nome() !== p.nome || this.trigger() !== p.trigger || this.genere() !== p.genere ||
      this.descrizione() !== p.descrizione || this.storia() !== (p.storia ?? '');
  });

  constructor() {
    // anteprima del prompt mentre si cambiano le scelte
    effect(() => {
      if (!this.proposteAperte()) return;
      const c = this.scelte();
      this.personaggio().descrizione;
      if (!c.checkpoint) return;
      if (this.timerAnteprima) clearTimeout(this.timerAnteprima);
      this.timerAnteprima = setTimeout(() => {
        this.api.anteprimaProposte(this.progetto(), this.personaggio().id, c)
          .then((a) => this.anteprima.set(a)).catch(() => this.anteprima.set(null));
      }, 350);
    });
    effect(() => {
      const e = this.eventi.proposte();
      if (e && e.progetto === untracked(this.progetto) && e.personaggio === untracked(this.personaggio).id) {
        untracked(() => void this.caricaProposte(true));
      }
    });
    effect(() => {
      const p = this.personaggio();
      this.nome.set(p.nome);
      this.trigger.set(p.trigger);
      this.genere.set(p.genere);
      this.descrizione.set(p.descrizione);
      this.storia.set(p.storia ?? '');
      this.adulto.set(p.adulto ?? null);
    });
  }

  protected async salva() {
    this.occupato.set(true);
    try {
      const p = await this.api.modificaPersonaggio(this.progetto(), this.personaggio().id, {
        nome: this.nome().trim(), trigger: this.trigger().trim(), genere: this.genere(), descrizione: this.descrizione().trim(),
        storia: this.storia().trim(), ...(this.adulto() !== null ? { adulto: this.adulto() } : {}),
      });
      this.cambiato.emit(p);
      this.avvisi.ok(`${p.nome} salvato`);
    } catch (e) {
      this.avvisi.errore(e);
    } finally {
      this.occupato.set(false);
    }
  }

  protected annulla() {
    const p = this.personaggio();
    this.nome.set(p.nome);
    this.trigger.set(p.trigger);
    this.genere.set(p.genere);
    this.descrizione.set(p.descrizione);
    this.storia.set(p.storia ?? '');
    this.adulto.set(p.adulto ?? null);
    this.note.set('');
  }

  protected async ricava() {
    if (!(await this.sceltaIA.pronta('Per ricavare i tratti dalla descrizione libera serve l’IA locale.'))) return;
    this.ricavando.set(true);
    this.note.set('');
    try {
      const l = await this.api.ricavaTratti(this.progetto(), this.personaggio().id, this.storia());
      const fine = await this.eventi.attendi(l.id);
      if (fine.stato !== 'completato') {
        if (fine.errore) this.avvisi.errore(fine.errore);
        return;
      }
      const r = (await this.api.lavoro<TrattiRicavati>(l.id)).risultato;
      if (!r) return;
      this.descrizione.set(r.descrizione);
      if (r.genere) this.genere.set(r.genere);
      this.adulto.set(r.adulto);
      const parti = [r.eta_apparente ? `età apparente: ${r.eta_apparente}` : '',
        r.non_rappresentabile.length ? `non disegnabile: ${r.non_rappresentabile.join('; ')}` : ''].filter(Boolean);
      this.note.set(parti.join(' · '));
      this.avvisi.ok('Tratti ricavati: controllali e premi Salva');
    } catch (e) {
      this.avvisi.errore(e);
    } finally {
      this.ricavando.set(false);
    }
  }

  protected async apriProposte() {
    this.proposteAperte.set(true);
    await this.caricaProposte(false);
    // si riparte dalle scelte dell'ultima volta (o da quelle del riferimento attuale)
    if (!this.precompilato) {
      this.precompilato = true;
      const r = [...this.proposte()].reverse().find((p) => p.ricetta)?.ricetta ?? this.personaggio().origine;
      if (r) this.precompila(r);
    }
    if (!this.elencoCheckpoint().length) {
      try {
        const m = await this.api.modelli();
        const ck = m['checkpoints'] ?? [];
        this.elencoLora.set(m['loras'] ?? []);
        this.elencoCheckpoint.set(ck);
        const prefer = [/illustrious/i, /noob/i, /pony/i, /xl/i];
        this.checkpoint.set(this.checkpoint() || prefer.map((r) => ck.find((x) => r.test(x))).find(Boolean) || ck[0] || '');
      } catch (e) {
        this.avvisi.errore(e);
      }
    }
  }

  private precompila(r: RicettaProposta) {
    this.checkpoint.set(r.checkpoint);
    this.lora.set(r.lora_stile);
    this.forzaLora.set(r.forza_lora);
    this.stile.set(r.stile);
    this.extra.set(r.extra);
    this.negativo.set(r.negativo ?? NEGATIVO_PROPOSTE);
    this.passi.set(r.passi);
    this.cfg.set(r.cfg);
    this.sampler.set(r.sampler);
    this.scheduler.set(r.scheduler);
    if (['figura_intera', 'mezzo_busto', 'primo_piano'].includes(r.inquadratura)) {
      this.inquadratura.set(r.inquadratura as InquadraturaProposta);
    }
    this.avanzate.set(!!r.negativo || r.passi !== 28 || r.cfg !== 6 || r.sampler !== 'euler_ancestral' || r.scheduler !== 'karras');
  }

  /** Riprende le scelte con cui è stata fatta una proposta. */
  protected usaScelte(p: Proposta) {
    if (p.ricetta) {
      this.precompila(p.ricetta);
      this.avvisi.ok('Scelte di quella proposta ripristinate');
    }
  }

  protected numeroValido(v: string, min: number, max: number, ripiego: number): number {
    const n = Number(String(v).replace(',', '.'));
    return Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : ripiego;
  }

  private async caricaProposte(aggiornaPersonaggio: boolean) {
    try {
      this.proposte.set(await this.api.proposte(this.progetto(), this.personaggio().id));
      if (aggiornaPersonaggio && !this.modificato()) {
        // l'IA può aver appena ricavato i tratti dalla descrizione libera
        const p = (await this.api.progetto(this.progetto())).personaggi.find((x) => x.id === this.personaggio().id);
        if (p && (p.descrizione !== this.personaggio().descrizione || p.genere !== this.personaggio().genere)) {
          this.cambiato.emit(p);
        }
      }
    } catch {
      /* riprova al prossimo evento */
    }
  }

  protected async generaProposte(da: string | null) {
    // senza tratti l'IA li ricava prima dalla descrizione libera
    if (!this.personaggio().descrizione.trim() && (this.personaggio().storia ?? '').trim()
      && !(await this.sceltaIA.pronta('Il personaggio ha solo la descrizione libera: per ricavarne i tratti serve l’IA locale.'))) return;
    try {
      const l = await this.api.generaProposte(this.progetto(), this.personaggio().id, {
        ...this.scelte(), numero: da ? Math.min(this.numero(), 4) : this.numero(), da,
      });
      const fine = await this.eventi.attendi(l.id);
      if (fine.stato === 'errore' && fine.errore) this.avvisi.errore(fine.errore);
      await this.caricaProposte(true);
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected async usa(file: string) {
    this.occupato.set(true);
    try {
      const p = await this.api.scegliProposta(this.progetto(), this.personaggio().id, file);
      this.cambiato.emit({ ...p, creato: Date.now() / 1000 });
      this.proposte.update((l) => l.map((x) => ({ ...x, scelta: x.file === file })));
      this.avvisi.ok(p.origine ? `Immagine di riferimento di ${p.nome} impostata: il dataset userà le stesse scelte`
        : `Immagine di riferimento di ${p.nome} impostata`);
    } catch (e) {
      this.avvisi.errore(e);
    } finally {
      this.occupato.set(false);
    }
  }

  protected async scarta() {
    if (!confirm('Spostare nel cestino del progetto le proposte non scelte?')) return;
    try {
      await this.api.scartaProposte(this.progetto(), this.personaggio().id);
      await this.caricaProposte(false);
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected async ferma(id: string) {
    await this.api.annulla(id).catch((e) => this.avvisi.errore(e));
  }

  protected urlProposta(file: string) {
    return this.api.urlProposta(this.progetto(), this.personaggio().id, file);
  }

  protected async suggerisci() {
    try {
      this.trigger.set((await this.api.suggerisciTrigger(this.nome() || 'personaggio', this.progetto())).trigger);
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected async carica(file: File | undefined | null) {
    if (!file) return;
    if (!file.type.startsWith('image/')) {
      this.avvisi.errore(new Error('Scegli un file immagine (PNG, JPG o WebP).'));
      return;
    }
    this.occupato.set(true);
    try {
      const p = await this.api.caricaRiferimento(this.progetto(), this.personaggio().id, file);
      this.cambiato.emit({ ...p, creato: Date.now() / 1000 });  // forza il ricaricamento dell'anteprima
    } catch (e) {
      this.avvisi.errore(e);
    } finally {
      this.occupato.set(false);
    }
  }

  protected scelto(ev: Event) {
    const input = ev.target as HTMLInputElement;
    void this.carica(input.files?.[0]);
    input.value = '';
  }

  protected rilasciato(ev: DragEvent) {
    ev.preventDefault();
    this.trascina.set(false);
    void this.carica(ev.dataTransfer?.files?.[0]);
  }

  protected async elimina() {
    const p = this.personaggio();
    if (!confirm(`Eliminare ${p.nome}? I suoi file finiscono nel cestino del progetto.`)) return;
    try {
      await this.api.eliminaPersonaggio(this.progetto(), p.id);
      this.eliminato.emit(p.id);
    } catch (e) {
      this.avvisi.errore(e);
    }
  }
}
