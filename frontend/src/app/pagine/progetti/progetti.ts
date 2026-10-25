import { DatePipe } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatMenuModule } from '@angular/material/menu';
import { Router } from '@angular/router';
import { ApiService } from '../../core/api.service';
import { AvvisiService } from '../../core/avvisi.service';
import { Progetto } from '../../core/modelli';
import { ProgettoService } from '../../core/progetto.service';

@Component({
  selector: 'app-progetti',
  imports: [DatePipe, FormsModule, MatButtonModule, MatFormFieldModule, MatIconModule, MatInputModule, MatMenuModule],
  templateUrl: './progetti.html',
  styleUrl: './progetti.scss',
})
export class ProgettiPage implements OnInit {
  protected progetti = inject(ProgettoService);
  private api = inject(ApiService);
  private avvisi = inject(AvvisiService);
  private router = inject(Router);

  protected nuovoAperto = signal(false);
  protected nome = signal('');
  protected descrizione = signal('');
  protected caricato = signal(false);

  async ngOnInit() {
    this.progetti.chiudi();
    try {
      await this.progetti.aggiornaElenco();
    } catch (e) {
      this.avvisi.errore(e);
    } finally {
      this.caricato.set(true);
    }
    if (!this.progetti.elenco().length) this.nuovoAperto.set(true);
  }

  protected async crea() {
    const nome = this.nome().trim();
    if (!nome) return;
    try {
      const p = await this.api.creaProgetto(nome, this.descrizione().trim());
      this.nome.set('');
      this.descrizione.set('');
      await this.router.navigate(['/progetto', p.id, 'personaggi']);
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected apri(p: Progetto) {
    void this.router.navigate(['/progetto', p.id, 'personaggi']);
  }

  protected async elimina(p: Progetto) {
    if (!confirm(`Spostare «${p.nome}» nel cestino? Potrai recuperarlo dalla cartella .cestino dei progetti.`)) return;
    try {
      await this.api.eliminaProgetto(p.id);
      await this.progetti.aggiornaElenco();
      this.avvisi.ok('Progetto spostato nel cestino');
    } catch (e) {
      this.avvisi.errore(e);
    }
  }
}
