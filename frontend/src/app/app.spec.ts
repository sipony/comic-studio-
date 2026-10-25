import { HttpErrorResponse } from '@angular/common/http';
import { describe, expect, it } from 'vitest';
import { messaggioErrore } from './core/api.service';
import { gb } from './core/modelli';

describe('messaggioErrore', () => {
  it('usa il dettaglio del backend', () => {
    const e = new HttpErrorResponse({ status: 400, error: { detail: 'Trigger già usata' } });
    expect(messaggioErrore(e)).toBe('Trigger già usata');
  });

  it('unisce gli errori di validazione', () => {
    const e = new HttpErrorResponse({ status: 422, error: { detail: [{ msg: 'campo mancante' }, { msg: 'troppo lungo' }] } });
    expect(messaggioErrore(e)).toBe('campo mancante; troppo lungo');
  });

  it('spiega quando il programma non risponde', () => {
    expect(messaggioErrore(new HttpErrorResponse({ status: 0 }))).toContain('non risponde');
  });
});

describe('gb', () => {
  it('formatta i byte in GB', () => {
    expect(gb(8 * 1024 ** 3)).toBe('8 GB');
    expect(gb(null)).toBe('—');
  });
});

import { apribile, eComfy, spezzaLink } from './core/link';

describe('indirizzi cliccabili nella console', () => {
  it('trova gli indirizzi di ComfyUI nei messaggi', () => {
    const p = spezzaLink('Connesso a ComfyUI 0.9.9 su http://127.0.0.1:8188 — GPU RTX 4070', 'localhost');
    expect(p.map((x) => x.testo)).toEqual(['Connesso a ComfyUI 0.9.9 su ', 'http://127.0.0.1:8188', ' — GPU RTX 4070']);
    expect(p[1].href).toBe('http://127.0.0.1:8188/');
  });

  it('accetta ip:porta senza schema e toglie la punteggiatura finale', () => {
    const p = spezzaLink('ComfyUI › To see the GUI go to: 0.0.0.0:8188.', 'localhost');
    expect(p[1]).toEqual({ testo: '0.0.0.0:8188', href: 'http://127.0.0.1:8188/' });
    expect(p[2].testo).toBe('.');
  });

  it('lascia stare il testo senza indirizzi', () => {
    expect(spezzaLink('Nessun indirizzo qui, solo 12:30')).toEqual([{ testo: 'Nessun indirizzo qui, solo 12:30' }]);
  });

  it('da un altro computer della rete punta all\'host di Comic Studio', () => {
    expect(apribile('http://127.0.0.1:8188', '192.168.1.20')).toBe('http://192.168.1.20:8188/');
  });

  it('riconosce ComfyUI', () => {
    expect(eComfy('http://127.0.0.1:8188/', 'http://127.0.0.1:8188')).toBe(true);
    expect(eComfy('http://127.0.0.1:8765/', 'http://127.0.0.1:8188')).toBe(false);
  });
});

import { azionePrincipale, filtraRighe } from './core/catalogo-ia';
import { CatalogoIA, RigaCatalogoIA, VarianteIA } from './core/modelli';

function variante(nome: string, dove: VarianteIA['dove'], installato = false): VarianteIA {
  return { nome, alias: [], quant: 'Q4_K_M', gb: 5.2, memoria_gb: 7.2, stimata: false, installato, attuale: false,
    dove, nota: '', punteggio: 1 };
}
function riga(famiglia: string, dimensione: string, dove: VarianteIA['dove']): RigaCatalogoIA {
  const v = variante(`${famiglia}:${dimensione.toLowerCase()}-q4_K_M`, dove);
  return { famiglia, dimensione, parametri: 8, attivi: null, descrizione: '', varianti: [v], migliore: v.nome, punteggio: 1, dove };
}

describe('scelta del modello dell\'IA', () => {
  const righe = [riga('qwen3', '14B', 'gpu'), riga('gemma3', '27B', 'misto'), riga('llama3.1', '70B', 'troppo')];

  it('mostra prima solo i modelli che girano sul computer, poi tutti', () => {
    expect(filtraRighe(righe, false, '').map((r) => r.famiglia)).toEqual(['qwen3', 'gemma3']);
    expect(filtraRighe(righe, true, '')).toHaveLength(3);
  });

  it('cerca per famiglia, dimensione e nome completo', () => {
    expect(filtraRighe(righe, true, 'gemma').map((r) => r.famiglia)).toEqual(['gemma3']);
    expect(filtraRighe(righe, true, 'qwen3:14').map((r) => r.famiglia)).toEqual(['qwen3']);
    expect(filtraRighe(righe, true, '70b-q4')).toHaveLength(1);
  });

  it('il pulsante dice cosa succede', () => {
    const stato = (raggiungibile: boolean, eseguibile: string | null) =>
      ({ stato: { tipo: 'ollama', raggiungibile, eseguibile } }) as unknown as CatalogoIA;
    expect(azionePrincipale(null, null)).toBe('Scegli un modello');
    expect(azionePrincipale(variante('qwen3:8b', 'gpu', true), stato(true, 'x'))).toBe('Usa questo');
    expect(azionePrincipale(variante('qwen3:8b', 'gpu'), stato(false, null))).toBe('Installa Ollama e scarica');
    expect(azionePrincipale(variante('qwen3:8b', 'gpu'), stato(true, 'x'))).toBe('Scarica e usa (5,2 GB)');
  });
});
