import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { ApiService } from '../../core/api.service';
import { AvvisiService } from '../../core/avvisi.service';
import { GENERI, Genere, Personaggio } from '../../core/modelli';
import { ProgettoService } from '../../core/progetto.service';
import { SchedaPersonaggio } from './scheda-personaggio';

@Component({
  selector: 'app-personaggi',
  imports: [FormsModule, MatButtonModule, MatFormFieldModule, MatIconModule, MatInputModule, MatSelectModule, SchedaPersonaggio],
  templateUrl: './personaggi.html',
  styleUrl: './personaggi.scss',
})
export class PersonaggiPage {
  protected progetti = inject(ProgettoService);
  private api = inject(ApiService);
  private avvisi = inject(AvvisiService);
  protected generi = GENERI;

  protected progetto = computed(() => this.progetti.corrente()!);
  protected senzaRiferimento = computed(() => this.progetto().personaggi.filter((p) => !p.riferimento).length);

  protected nuovoNome = signal('');
  protected nuovoGenere = signal<Genere>('1girl');
  protected aggiungendo = signal(false);

  protected async aggiungi() {
    const nome = this.nuovoNome().trim();
    if (!nome) return;
    this.aggiungendo.set(true);
    try {
      const c = await this.api.aggiungiPersonaggio(this.progetto().id, { nome, genere: this.nuovoGenere(), descrizione: '' });
      this.aggiorna({ ...this.progetto(), personaggi: [...this.progetto().personaggi, c] });
      this.nuovoNome.set('');
    } catch (e) {
      this.avvisi.errore(e);
    } finally {
      this.aggiungendo.set(false);
    }
  }

  protected cambiato(c: Personaggio) {
    this.aggiorna({ ...this.progetto(), personaggi: this.progetto().personaggi.map((x) => (x.id === c.id ? c : x)) });
  }

  protected eliminato(id: string) {
    this.aggiorna({ ...this.progetto(), personaggi: this.progetto().personaggi.filter((x) => x.id !== id) });
  }

  private aggiorna(p = this.progetto()) {
    this.progetti.aggiornaCorrente(p);
  }
}
