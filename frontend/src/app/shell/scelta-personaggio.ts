import { Component, effect, inject, input, model, untracked } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { ActivatedRoute, Router } from '@angular/router';
import { Personaggio } from '../core/modelli';

/** Riga di "chip" per scegliere il personaggio su cui lavorare; ricorda la scelta nell'indirizzo (?p=). */
@Component({
  selector: 'app-scelta-personaggio',
  imports: [MatIconModule],
  template: `
    <nav aria-label="Personaggio">
      @for (p of personaggi(); track p.id) {
        <button class="chip" [class.attivo]="p.id === scelto()" (click)="scegli(p.id)">
          @if (p.riferimento) {
            <img [src]="'/api/progetti/' + progetto() + '/personaggi/' + p.id + '/riferimento'" alt="" />
          } @else {
            <mat-icon>person</mat-icon>
          }
          <span>{{ p.nome }}</span>
        </button>
      }
    </nav>
  `,
  styles: `
    nav { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 20px; }
    .chip { display: flex; align-items: center; gap: 8px; height: 40px; padding: 0 16px 0 4px; border-radius: 20px;
      border: 1px solid var(--mat-sys-outline-variant); background: var(--mat-sys-surface-container);
      color: var(--mat-sys-on-surface); font: inherit; font-weight: 500; cursor: pointer; }
    .chip img, .chip mat-icon { width: 32px; height: 32px; border-radius: 50%; object-fit: cover; object-position: top; background: #fff; }
    .chip mat-icon { display: grid; place-items: center; background: var(--mat-sys-surface-container-highest); font-size: 20px; }
    .chip.attivo { border-color: var(--mat-sys-primary); background: var(--mat-sys-secondary-container);
      color: var(--mat-sys-on-secondary-container); }
  `,
})
export class SceltaPersonaggio {
  readonly progetto = input.required<string>();
  readonly personaggi = input.required<Personaggio[]>();
  readonly scelto = model<string | null>(null);
  private route = inject(ActivatedRoute);
  private router = inject(Router);

  constructor() {
    effect(() => {
      const elenco = this.personaggi();
      untracked(() => {
        const daQuery = this.route.snapshot.queryParamMap.get('p');
        if (!elenco.length) return this.scelto.set(null);
        if (!this.scelto() || !elenco.some((p) => p.id === this.scelto())) {
          this.scelto.set(elenco.some((p) => p.id === daQuery) ? daQuery : elenco[0].id);
        }
      });
    });
  }

  protected scegli(id: string) {
    if (id === this.scelto()) return;
    this.scelto.set(id);
    void this.router.navigate([], { queryParams: { p: id }, replaceUrl: true, queryParamsHandling: 'merge' });
  }
}
