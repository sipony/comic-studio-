import { Component, computed, effect, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ApiService } from '../../core/api.service';
import { AvvisiService } from '../../core/avvisi.service';
import { GENERI, Genere, Personaggio } from '../../core/modelli';

@Component({
  selector: 'app-scheda-personaggio',
  imports: [FormsModule, MatButtonModule, MatFormFieldModule, MatIconModule, MatInputModule, MatSelectModule, MatTooltipModule],
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
  protected generi = GENERI;

  protected nome = signal('');
  protected trigger = signal('');
  protected genere = signal<Genere>('1girl');
  protected descrizione = signal('');
  protected trascina = signal(false);
  protected occupato = signal(false);

  protected immagine = computed(() => this.api.urlRiferimento(this.progetto(), this.personaggio()));
  protected modificato = computed(() => {
    const p = this.personaggio();
    return this.nome() !== p.nome || this.trigger() !== p.trigger || this.genere() !== p.genere ||
      this.descrizione() !== p.descrizione;
  });

  constructor() {
    effect(() => {
      const p = this.personaggio();
      this.nome.set(p.nome);
      this.trigger.set(p.trigger);
      this.genere.set(p.genere);
      this.descrizione.set(p.descrizione);
    });
  }

  protected async salva() {
    this.occupato.set(true);
    try {
      const p = await this.api.modificaPersonaggio(this.progetto(), this.personaggio().id, {
        nome: this.nome().trim(), trigger: this.trigger().trim(), genere: this.genere(), descrizione: this.descrizione().trim(),
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
