import { Component, effect, inject, input, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { Router, RouterOutlet } from '@angular/router';
import { AvvisiService } from '../../core/avvisi.service';
import { ProgettoService } from '../../core/progetto.service';

/** Contenitore delle pagine di un progetto: lo carica e lo rende disponibile a tutti gli step. */
@Component({
  selector: 'app-progetto',
  imports: [RouterOutlet, MatButtonModule, MatIconModule],
  template: `
    @if (errore()) {
      <div class="pagina">
        <h1>Progetto non disponibile</h1>
        <p class="sotto">{{ errore() }}</p>
        <button mat-flat-button (click)="torna()"><mat-icon>arrow_back</mat-icon> Torna ai progetti</button>
      </div>
    } @else if (progetti.corrente()?.id === id()) {
      <router-outlet />
    }
  `,
})
export class ProgettoPage {
  readonly id = input.required<string>();
  protected progetti = inject(ProgettoService);
  private avvisi = inject(AvvisiService);
  private router = inject(Router);
  protected errore = signal<string | null>(null);

  constructor() {
    effect(() => {
      const id = this.id();
      this.errore.set(null);
      this.progetti.apri(id).catch((e) => {
        this.errore.set(e instanceof Error ? e.message : String(e));
        this.avvisi.errore(e);
      });
    });
  }

  protected torna() {
    void this.router.navigateByUrl('/progetti');
  }
}
