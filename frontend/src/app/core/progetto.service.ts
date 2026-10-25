import { Injectable, computed, inject, signal } from '@angular/core';
import { ApiService } from './api.service';
import { Progetto } from './modelli';

/** Il progetto aperto e l'elenco dei progetti. */
@Injectable({ providedIn: 'root' })
export class ProgettoService {
  private api = inject(ApiService);

  readonly elenco = signal<Progetto[]>([]);
  readonly corrente = signal<Progetto | null>(null);
  readonly id = computed(() => this.corrente()?.id ?? null);

  async aggiornaElenco() {
    this.elenco.set(await this.api.progetti());
  }

  async apri(id: string) {
    const p = await this.api.progetto(id);
    this.corrente.set(p);
    return p;
  }

  aggiornaCorrente(p: Progetto) {
    this.corrente.set(p);
    this.elenco.update((l) => l.map((x) => (x.id === p.id ? p : x)));
  }

  chiudi() {
    this.corrente.set(null);
  }
}
