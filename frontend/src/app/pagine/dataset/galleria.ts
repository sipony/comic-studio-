import { DecimalPipe } from '@angular/common';
import { Component, HostListener, computed, inject, input, output, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatMenuModule } from '@angular/material/menu';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ApiService } from '../../core/api.service';
import { AvvisiService } from '../../core/avvisi.service';
import { ImmagineDataset, Lavoro, Personaggio, RiepilogoDataset, StatoImmagine } from '../../core/modelli';

type Filtro = 'tutte' | 'tenuta' | 'scartata' | 'da_decidere';
type Ordine = 'numero' | 'punteggio';

@Component({
  selector: 'app-galleria',
  imports: [DecimalPipe, MatButtonModule, MatIconModule, MatMenuModule, MatTooltipModule],
  templateUrl: './galleria.html',
  styleUrl: './galleria.scss',
})
export class Galleria {
  readonly progetto = input.required<string>();
  readonly personaggio = input.required<Personaggio>();
  readonly immagini = input.required<ImmagineDataset[]>();
  readonly riepilogo = input<RiepilogoDataset | null>(null);
  readonly daTenere = input(30);
  readonly lavoro = input<Lavoro | null>(null);
  readonly ricarica = output<void>();

  private api = inject(ApiService);
  private avvisi = inject(AvvisiService);

  protected filtro = signal<Filtro>('tutte');
  protected ordine = signal<Ordine>('numero');
  protected grandi = signal(false);
  protected aperta = signal<string | null>(null);

  protected visibili = computed(() => {
    const f = this.filtro();
    let l = this.immagini().filter((i) => f === 'tutte' || (f === 'da_decidere' ? i.stato === null : i.stato === f));
    if (this.ordine() === 'punteggio') l = [...l].sort((a, b) => (b.punteggio ?? -1) - (a.punteggio ?? -1));
    else l = [...l].sort((a, b) => b.numero - a.numero);
    return l;
  });
  protected corrente = computed(() => this.visibili().find((i) => i.file === this.aperta()) ?? null);
  protected haPunteggi = computed(() => this.immagini().some((i) => i.punteggio !== null));

  protected url(i: ImmagineDataset, anteprima = true) {
    return this.api.urlImmagine(this.progetto(), this.personaggio().id, i.file, anteprima) + `${anteprima ? '&' : '?'}v=${i.creato}`;
  }

  protected async stato(i: ImmagineDataset, s: StatoImmagine, ev?: Event) {
    ev?.stopPropagation();
    const nuovo = i.stato === s ? null : s;
    try {
      await this.api.statoImmagine(this.progetto(), this.personaggio().id, i.file, nuovo);
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected async selezioneAutomatica() {
    try {
      await this.api.selezionaAuto(this.progetto(), this.personaggio().id, this.daTenere());
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected async eliminaScartate() {
    const n = this.riepilogo()?.scartate ?? 0;
    if (!n || !confirm(`Spostare nel cestino le ${n} immagini scartate?`)) return;
    try {
      await this.api.eliminaImmagini(this.progetto(), this.personaggio().id, { scartate: true });
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected sposta(delta: number) {
    const l = this.visibili();
    const i = l.findIndex((x) => x.file === this.aperta());
    const j = i + delta;
    if (i >= 0 && j >= 0 && j < l.length) this.aperta.set(l[j].file);
  }

  @HostListener('document:keydown', ['$event'])
  protected tasto(ev: KeyboardEvent) {
    const c = this.corrente();
    if (!c || (ev.target as HTMLElement)?.closest('input, textarea, select')) return;
    const azioni: Record<string, () => void> = {
      Escape: () => this.aperta.set(null),
      ArrowRight: () => this.sposta(1),
      ArrowLeft: () => this.sposta(-1),
      t: () => void this.stato(c, 'tenuta').then(() => this.sposta(1)),
      s: () => void this.stato(c, 'scartata').then(() => this.sposta(1)),
    };
    const a = azioni[ev.key];
    if (a) {
      ev.preventDefault();
      a();
    }
  }
}
