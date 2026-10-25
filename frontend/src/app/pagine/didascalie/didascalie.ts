import { PercentPipe } from '@angular/common';
import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSliderModule } from '@angular/material/slider';
import { MatTooltipModule } from '@angular/material/tooltip';
import { RouterLink } from '@angular/router';
import { ApiService } from '../../core/api.service';
import { AvvisiService } from '../../core/avvisi.service';
import { EventiService } from '../../core/eventi.service';
import { ConfigDidascalie, FrequenzaTag, RigaDidascalia, StatoDidascalie } from '../../core/modelli';
import { ProgettoService } from '../../core/progetto.service';
import { SceltaPersonaggio } from '../../shell/scelta-personaggio';

type FiltroTag = 'tutti' | 'suggeriti' | 'rimossi';

@Component({
  selector: 'app-didascalie',
  imports: [PercentPipe, FormsModule, MatButtonModule, MatButtonToggleModule, MatFormFieldModule, MatIconModule,
    MatInputModule, MatProgressBarModule, MatSlideToggleModule, MatSliderModule, MatTooltipModule, RouterLink, SceltaPersonaggio],
  templateUrl: './didascalie.html',
  styleUrl: './didascalie.scss',
})
export class DidascaliePage {
  protected progetti = inject(ProgettoService);
  private api = inject(ApiService);
  private avvisi = inject(AvvisiService);
  private eventi = inject(EventiService);

  protected progetto = computed(() => this.progetti.corrente()!);
  protected personaggi = computed(() => this.progetto().personaggi);
  protected sceltoId = signal<string | null>(null);
  protected personaggio = computed(() => this.personaggi().find((p) => p.id === this.sceltoId()) ?? null);

  protected stato = signal<StatoDidascalie | null>(null);
  protected config = signal<ConfigDidascalie | null>(null);
  protected filtroTag = signal<FiltroTag>('tutti');
  protected cercaTag = signal('');
  protected salvando = signal(false);

  protected lavoro = computed(() => {
    const p = this.personaggio();
    return p ? this.eventi.attivi().find((l) => l.tipo === 'didascalie_analizza' && l.titolo.endsWith(p.nome)) ?? null : null;
  });
  protected tag = computed(() => {
    const f = this.filtroTag();
    const q = this.cercaTag().trim().toLowerCase();
    return (this.stato()?.frequenze ?? []).filter((t) =>
      (f === 'tutti' || (f === 'suggeriti' ? t.suggerito : t.rimosso)) && (!q || t.tag.includes(q)));
  });
  protected suggeriti = computed(() => (this.stato()?.frequenze ?? []).filter((t) => t.suggerito));
  protected daAnalizzare = computed(() => {
    const s = this.stato();
    return s ? s.totale - s.analizzate : 0;
  });
  protected usaTagger = computed(() => this.config()?.modalita !== 'prompt');

  private timer?: ReturnType<typeof setTimeout>;
  private ultimoInviato = '';

  constructor() {
    effect(() => {
      const id = this.sceltoId();
      if (id) untracked(() => void this.carica());
    });
    effect(() => {
      const e = this.eventi.didascalie();
      if (e && e.progetto === this.progetto().id && e.personaggio === untracked(this.sceltoId)) untracked(() => void this.carica());
    });
  }

  protected async carica() {
    const id = this.sceltoId();
    if (!id) return;
    try {
      const s = await this.api.statoDidascalie(this.progetto().id, id);
      if (id !== this.sceltoId()) return;
      this.stato.set(s);
      this.config.set(s.config);
      this.ultimoInviato = JSON.stringify(s.config);
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  /** Cambia la configurazione: le didascalie automatiche si ricalcolano subito dopo. */
  protected cambia(f: (c: ConfigDidascalie) => ConfigDidascalie) {
    const c = this.config();
    if (!c) return;
    this.config.set(f(structuredClone(c)));
    clearTimeout(this.timer);
    this.timer = setTimeout(() => void this.salva(), 350);
  }

  private async salva() {
    const c = this.config();
    const id = this.sceltoId();
    if (!c || !id) return;
    const json = JSON.stringify(c);
    if (json === this.ultimoInviato) return;
    this.salvando.set(true);
    try {
      this.ultimoInviato = json;
      const s = await this.api.salvaConfigDidascalie(this.progetto().id, id, c);
      if (JSON.stringify(this.config()) === json) this.stato.set(s);
    } catch (e) {
      this.avvisi.errore(e);
    } finally {
      this.salvando.set(false);
    }
  }

  protected imposta<K extends keyof ConfigDidascalie>(k: K, v: ConfigDidascalie[K]) {
    this.cambia((c) => ({ ...c, [k]: v }));
  }

  protected elenco(v: string[]): string {
    return v.join(', ');
  }

  protected impostaElenco(k: 'aggiunti', testo: string) {
    this.imposta(k, testo.split(',').map((x) => x.trim()).filter(Boolean));
  }

  protected alterna(t: FrequenzaTag) {
    if (t.fisso) {
      this.avvisi.ok('È un tratto fisso preso dalla descrizione: togli l’opzione «Togli i tratti fissi» per tenerlo.');
      return;
    }
    this.cambia((c) => ({
      ...c, rimossi: t.rimosso ? c.rimossi.filter((x) => x !== t.tag) : [...c.rimossi, t.tag],
    }));
  }

  protected togliSuggeriti() {
    const via = this.suggeriti().map((t) => t.tag);
    this.cambia((c) => ({ ...c, rimossi: [...new Set([...c.rimossi, ...via])] }));
  }

  protected sostituisci(t: FrequenzaTag) {
    const nuovo = prompt(`Sostituire «${t.tag}» con (vuoto = annulla la sostituzione):`, t.sostituito ?? t.tag);
    if (nuovo === null) return;
    this.cambia((c) => {
      const s = { ...c.sostituzioni };
      if (!nuovo.trim() || nuovo.trim() === t.tag) delete s[t.tag];
      else s[t.tag] = nuovo.trim();
      return { ...c, sostituzioni: s };
    });
  }

  protected async analizza(tutte = false) {
    const id = this.sceltoId();
    if (!id) return;
    try {
      await this.api.analizzaTag(this.progetto().id, id, tutte);
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected async annulla(lid: string) {
    await this.api.annulla(lid).catch((e) => this.avvisi.errore(e));
  }

  protected async scrivi(r: RigaDidascalia, testo: string) {
    const pulito = testo.trim();
    if (pulito === r.testo.trim()) return;
    try {
      await this.api.scriviDidascalia(this.progetto().id, this.sceltoId()!, r.file, pulito);
      this.aggiornaRiga(r.file, { testo: pulito, manuale: true });
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected async ripristina(r: RigaDidascalia) {
    try {
      await this.api.ripristinaDidascalia(this.progetto().id, this.sceltoId()!, r.file);
      this.aggiornaRiga(r.file, { testo: r.auto, manuale: false });
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  private aggiornaRiga(file: string, campi: Partial<RigaDidascalia>) {
    this.stato.update((s) => (s ? { ...s, immagini: s.immagini.map((x) => (x.file === file ? { ...x, ...campi } : x)) } : s));
  }

  protected url(r: RigaDidascalia) {
    return this.api.urlImmagine(this.progetto().id, this.sceltoId()!, r.file, true) + `&v=${r.creato}`;
  }

  protected urlZip() {
    return this.api.urlZipDataset(this.progetto().id, this.sceltoId()!);
  }
}
