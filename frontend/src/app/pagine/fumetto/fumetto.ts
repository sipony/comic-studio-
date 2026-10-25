import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatMenuModule } from '@angular/material/menu';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';
import { MatTooltipModule } from '@angular/material/tooltip';
import { RouterLink } from '@angular/router';
import { ApiService } from '../../core/api.service';
import { AvvisiService } from '../../core/avvisi.service';
import { EventiService } from '../../core/eventi.service';
import {
  Dialogo, FormatoVignetta, Fumetto, ImmaginiVignetta, ImpostazioniFumetto, Pagina, Personaggio, PosizioneBalloon, PromptScena,
  Vignetta,
} from '../../core/modelli';
import { ProgettoService } from '../../core/progetto.service';

const ESEMPIO = `# Una vignetta per riga:  formato | personaggi | cosa succede (in inglese) | chi: battuta | …
# formato: larga, alta (due alte di fila stanno affiancate), quadrata
# personaggi: per nome, separati da +  (il primo sta a sinistra);  nessuno = solo ambiente
larga | nessuno | police station at night, rain, neon sign | narratore: Distretto 9, ore 23:40.
alta | {A} | close-up, serious expression, talking | {A}: Nessun mittente. Solo una mappa.
---
larga | {A} + {B} | walking out of a police station at night, rain | {B}: Prendi l'auto.`;

function nuovoId() {
  return Math.random().toString(16).slice(2, 12);
}

@Component({
  selector: 'app-fumetto',
  imports: [FormsModule, MatButtonModule, MatButtonToggleModule, MatFormFieldModule, MatIconModule, MatInputModule, MatMenuModule,
    MatProgressBarModule, MatSelectModule, MatTooltipModule, RouterLink],
  templateUrl: './fumetto.html',
  styleUrl: './fumetto.scss',
})
export class FumettoPage {
  protected progetti = inject(ProgettoService);
  private api = inject(ApiService);
  private avvisi = inject(AvvisiService);
  protected eventi = inject(EventiService);

  protected progetto = computed(() => this.progetti.corrente()!);
  protected personaggi = computed(() => this.progetto().personaggi);
  protected nomi = computed(() => Object.fromEntries(this.personaggi().map((p) => [p.id, p.nome])) as Record<string, string>);

  protected fumetto = signal<Fumetto | null>(null);
  protected immagini = signal<Record<string, ImmaginiVignetta>>({});
  protected lora = signal<Record<string, string | null>>({});
  protected sceltaId = signal<string | null>(null);
  protected paginaAnteprima = signal(0);
  protected versioneAnteprima = signal(0);
  protected impostazioniAperte = signal(false);
  protected importaAperto = signal(false);
  protected testoStoria = signal('');
  protected testoLibero = signal('');
  protected modoStoria = signal<'libera' | 'righe'>('libera');
  protected promptScelta = signal<{ aggiornata: boolean; prompt: PromptScena | null } | null>(null);
  protected checkpoint = signal<string[]>([]);
  protected loraElenco = signal<string[]>([]);
  protected salvataggio = signal<'salvato' | 'modificato' | 'errore'>('salvato');

  protected tutte = computed(() => (this.fumetto()?.pagine ?? []).flatMap((p, pi) => p.vignette.map((v, vi) => ({ v, pi, vi }))));
  protected scelta = computed(() => this.tutte().find((x) => x.v.id === this.sceltaId()) ?? null);
  protected numero = computed(() => Object.fromEntries(this.tutte().map((x, i) => [x.v.id, i + 1])) as Record<string, number>);
  protected mancanti = computed(() => this.tutte().filter((x) => !this.immagini()[x.v.id]?.versioni.length).length);
  protected lavoro = computed(() =>
    this.eventi.attivi().find((l) => ['fumetto_genera', 'fumetto_analisi', 'fumetto_storia'].includes(l.tipo) &&
      l.progetto === this.progetto().id) ?? null);
  protected senzaLora = computed(() => this.personaggi().filter((p) => !this.lora()[p.id]));

  private timer?: ReturnType<typeof setTimeout>;
  private inviato = '';

  constructor() {
    void this.carica();
    void this.api.modelli().then((m) => {
      this.checkpoint.set(m['checkpoints'] ?? []);
      this.loraElenco.set(m['loras'] ?? []);
    }).catch(() => undefined);
    effect(() => {
      const e = this.eventi.fumetto();
      if (!e || e.progetto !== untracked(this.progetto).id) return;
      // senza modifiche in sospeso si ricarica tutto (l'IA può aver scelto i personaggi o creato vignette)
      untracked(() => void (this.salvataggio() === 'salvato' ? this.carica() : this.caricaImmagini()));
    });
    effect(() => {
      const id = this.sceltaId();
      const testo = this.scelta()?.v.descrizione ?? '';
      untracked(() => void this.caricaPrompt(id, testo));
    });
  }

  private async carica() {
    try {
      const s = await this.api.fumetto(this.progetto().id);
      this.inviato = JSON.stringify(s.fumetto);
      this.fumetto.set(s.fumetto);
      this.immagini.set(s.immagini);
      this.lora.set(s.lora);
      if (!this.sceltaId()) this.sceltaId.set(this.tutte()[0]?.v.id ?? null);
      this.versioneAnteprima.update((n) => n + 1);
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  private async caricaPrompt(id: string | null, testo: string) {
    if (!id || !testo.trim()) {
      this.promptScelta.set(null);
      return;
    }
    try {
      this.promptScelta.set(await this.api.promptVignetta(this.progetto().id, id));
    } catch {
      this.promptScelta.set(null);
    }
  }

  protected async analizza(id: string) {
    if (!(await this.salva())) return;
    try {
      const fine = await this.eventi.attendi((await this.api.analizzaVignetta(this.progetto().id, id)).id);
      if (fine.stato !== 'completato' && fine.errore) this.avvisi.errore(fine.errore);
      await this.carica();
      await this.caricaPrompt(id, this.scelta()?.v.descrizione ?? '');
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected async rafforza(id: string, mancanti: string[]) {
    this.cambiaVignetta((v) => (v.rafforza = [...new Set([...(v.rafforza ?? []), ...mancanti])]));
    await this.genera(id, true);
  }

  protected togliRafforzo(t: string) {
    this.cambiaVignetta((v) => (v.rafforza = (v.rafforza ?? []).filter((x) => x !== t)));
  }

  protected async storiaIA(sostituisci: boolean) {
    if (sostituisci && !confirm('Sostituire tutte le pagine attuali con questa storia?')) return;
    try {
      clearTimeout(this.timer);
      await this.salva();
      const l = await this.api.storiaIA(this.progetto().id, this.testoLibero(), sostituisci);
      this.importaAperto.set(false);
      const fine = await this.eventi.attendi(l.id);
      if (fine.stato !== 'completato' && fine.errore) this.avvisi.errore(fine.errore);
      await this.carica();
      this.sceltaId.set(this.tutte()[0]?.v.id ?? null);
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  private async caricaImmagini() {
    try {
      const s = await this.api.fumetto(this.progetto().id);
      this.immagini.set(s.immagini);
      this.versioneAnteprima.update((n) => n + 1);
    } catch {
      /* riprova al prossimo evento */
    }
  }

  // ------------------------------------------------------------ modifiche e salvataggio

  private modifica(f: (x: Fumetto) => void) {
    const c = this.fumetto();
    if (!c) return;
    const copia = structuredClone(c);
    f(copia);
    this.fumetto.set(copia);
    this.salvataggio.set('modificato');
    clearTimeout(this.timer);
    this.timer = setTimeout(() => void this.salva(), 600);
  }

  private async salva(): Promise<boolean> {
    const f = this.fumetto();
    if (!f) return false;
    const json = JSON.stringify(f);
    if (json === this.inviato) {
      this.salvataggio.set('salvato');
      return true;
    }
    try {
      await this.api.salvaFumetto(this.progetto().id, f);
      this.inviato = json;
      this.salvataggio.set(JSON.stringify(this.fumetto()) === json ? 'salvato' : 'modificato');
      this.versioneAnteprima.update((n) => n + 1);
      return true;
    } catch (e) {
      this.salvataggio.set('errore');
      this.avvisi.errore(e);
      return false;
    }
  }

  protected impostazione<K extends keyof ImpostazioniFumetto>(k: K, v: ImpostazioniFumetto[K]) {
    this.modifica((f) => (f.impostazioni[k] = v));
  }

  protected numeroImp<K extends keyof ImpostazioniFumetto>(k: K, testo: string) {
    const n = Number(String(testo).replace(',', '.'));
    if (Number.isFinite(n)) this.impostazione(k, n as ImpostazioniFumetto[K]);
  }

  private vignetta(f: Fumetto, id: string): Vignetta | undefined {
    for (const p of f.pagine) for (const v of p.vignette) if (v.id === id) return v;
    return undefined;
  }

  protected cambiaVignetta(f: (v: Vignetta) => void) {
    const id = this.sceltaId();
    if (!id) return;
    this.modifica((x) => {
      const v = this.vignetta(x, id);
      if (v) f(v);
    });
  }

  protected formato(v: FormatoVignetta) {
    this.cambiaVignetta((x) => (x.formato = v));
  }

  protected alternaPersonaggio(p: Personaggio) {
    this.cambiaVignetta((v) => {
      const i = v.personaggi.indexOf(p.id);
      if (i >= 0) v.personaggi.splice(i, 1);
      else if (v.personaggi.length < 3) v.personaggi.push(p.id);
      else this.avvisi.errore(new Error('Al massimo 3 personaggi per vignetta.'));
      if (v.personaggi.length >= 2 && v.formato !== 'larga') v.formato = 'larga';
    });
  }

  protected spostaPersonaggio(i: number, delta: number) {
    this.cambiaVignetta((v) => {
      const j = i + delta;
      if (j < 0 || j >= v.personaggi.length) return;
      [v.personaggi[i], v.personaggi[j]] = [v.personaggi[j], v.personaggi[i]];
    });
  }

  protected aggiungiDialogo() {
    this.cambiaVignetta((v) => v.dialoghi.push({ chi: v.personaggi[0] ?? 'narratore', testo: '', posizione: 'auto' }));
  }

  protected cambiaDialogo(i: number, campo: keyof Dialogo, valore: string) {
    this.cambiaVignetta((v) => {
      if (campo === 'posizione') v.dialoghi[i].posizione = valore as PosizioneBalloon;
      else v.dialoghi[i][campo] = valore;
    });
  }

  protected togliDialogo(i: number) {
    this.cambiaVignetta((v) => v.dialoghi.splice(i, 1));
  }

  protected seme(testo: string) {
    const n = testo.trim() ? Number(testo) : null;
    this.cambiaVignetta((v) => (v.seme = n !== null && Number.isFinite(n) ? Math.round(n) : null));
  }

  // ------------------------------------------------------------ pagine e vignette

  protected aggiungiPagina() {
    const v: Vignetta = { id: nuovoId(), formato: 'larga', personaggi: [], azione: '', descrizione: '', rafforza: [], dialoghi: [], seme: null };
    this.modifica((f) => f.pagine.push({ id: nuovoId(), vignette: [v] }));
    this.sceltaId.set(v.id);
    this.paginaAnteprima.set((this.fumetto()?.pagine.length ?? 1) - 1);
  }

  protected aggiungiVignetta(pi: number) {
    const v: Vignetta = { id: nuovoId(), formato: 'alta', personaggi: [], azione: '', descrizione: '', rafforza: [], dialoghi: [], seme: null };
    this.modifica((f) => f.pagine[pi].vignette.push(v));
    this.sceltaId.set(v.id);
    this.paginaAnteprima.set(pi);
  }

  protected spostaVignetta(pi: number, vi: number, delta: number) {
    this.modifica((f) => {
      const l = f.pagine[pi].vignette;
      const j = vi + delta;
      if (j >= 0 && j < l.length) [l[vi], l[j]] = [l[j], l[vi]];
      else if (j < 0 && pi > 0) f.pagine[pi - 1].vignette.push(...l.splice(vi, 1));
      else if (j >= l.length && pi < f.pagine.length - 1) f.pagine[pi + 1].vignette.unshift(...l.splice(vi, 1));
    });
  }

  protected eliminaVignetta(pi: number, vi: number) {
    if (!confirm('Eliminare questa vignetta? Le sue immagini restano nella cartella del progetto.')) return;
    this.modifica((f) => f.pagine[pi].vignette.splice(vi, 1));
    this.sceltaId.set(this.tutte()[0]?.v.id ?? null);
  }

  protected eliminaPagina(pi: number) {
    if (!confirm(`Eliminare la pagina ${pi + 1} con tutte le sue vignette?`)) return;
    this.modifica((f) => {
      f.pagine.splice(pi, 1);
      if (!f.pagine.length) f.pagine.push({ id: nuovoId(), vignette: [] });
    });
    this.paginaAnteprima.set(0);
  }

  protected scegli(id: string, pi: number) {
    this.sceltaId.set(id);
    this.paginaAnteprima.set(pi);
  }

  // ------------------------------------------------------------ generazione

  protected async genera(id: string | null, stessoSeme = false) {
    if (!(await this.salva())) return;
    try {
      await this.api.generaVignette(this.progetto().id, id ? [id] : null, stessoSeme);
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected async ferma(id: string) {
    await this.api.annulla(id).catch((e) => this.avvisi.errore(e));
  }

  protected async versione(id: string, indice: number) {
    try {
      const iv = await this.api.scegliVersione(this.progetto().id, id, indice);
      this.immagini.update((m) => ({ ...m, [id]: iv }));
      this.versioneAnteprima.update((n) => n + 1);
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected corrente(id: string) {
    const iv = this.immagini()[id];
    if (!iv?.versioni.length) return null;
    const i = iv.scelta !== null && iv.scelta < iv.versioni.length ? iv.scelta : iv.versioni.length - 1;
    return iv.versioni[i];
  }

  protected url(file: string) {
    return this.api.urlVignetta(this.progetto().id, file);
  }

  protected urlAnteprima() {
    return `${this.api.urlAnteprimaPagina(this.progetto().id, this.paginaAnteprima())}&v=${this.versioneAnteprima()}`;
  }

  protected urlEsporta(formato: 'pdf' | 'zip') {
    return this.api.urlEsporta(this.progetto().id, formato);
  }

  // ------------------------------------------------------------ storia da testo

  protected apriImporta() {
    const [a, b] = this.personaggi();
    this.testoStoria.set(this.testoStoria() || ESEMPIO.replaceAll('{A}', a?.nome ?? 'nome').replaceAll('{B}', b?.nome ?? a?.nome ?? 'nome'));
    this.importaAperto.set(true);
  }

  protected async importa(sostituisci: boolean) {
    if (sostituisci && !confirm('Sostituire tutte le pagine attuali con questa storia?')) return;
    try {
      clearTimeout(this.timer);
      await this.salva();
      const s = await this.api.importaStoria(this.progetto().id, this.testoStoria(), sostituisci);
      this.inviato = JSON.stringify(s.fumetto);
      this.fumetto.set(s.fumetto);
      this.immagini.set(s.immagini);
      this.importaAperto.set(false);
      this.sceltaId.set(this.tutte()[0]?.v.id ?? null);
      this.versioneAnteprima.update((n) => n + 1);
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected chiParla(v: Vignetta): { id: string; nome: string }[] {
    const ids = v.personaggi.length ? v.personaggi : this.personaggi().map((p) => p.id);
    return [{ id: 'narratore', nome: 'Narratore (didascalia)' }, ...ids.map((id) => ({ id, nome: this.nomi()[id] ?? id }))];
  }

  protected pagine(): Pagina[] {
    return this.fumetto()?.pagine ?? [];
  }
}
