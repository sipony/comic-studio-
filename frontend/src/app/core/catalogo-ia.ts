import { CatalogoIA, DoveIA, RigaCatalogoIA, VarianteIA } from './modelli';

export const ETICHETTE_DOVE: Record<DoveIA, string> = {
  gpu: 'Sulla GPU', misto: 'GPU + CPU', cpu: 'Solo CPU', troppo: 'Non entra',
};

/** Filtra le righe: solo quelle che girano su questo computer (o tutte) e per nome. */
export function filtraRighe(righe: RigaCatalogoIA[], tutti: boolean, cerca: string): RigaCatalogoIA[] {
  const q = cerca.trim().toLowerCase();
  return righe.filter((r) => (tutti || r.dove !== 'troppo')
    && (!q || `${r.famiglia}:${r.dimensione}`.toLowerCase().includes(q)
      || r.varianti.some((v) => v.nome.toLowerCase().includes(q))));
}

/** Testo del pulsante principale per la variante scelta. */
export function azionePrincipale(v: VarianteIA | null, c: CatalogoIA | null): string {
  if (!v) return 'Scegli un modello';
  if (v.installato) return 'Usa questo';
  if (c && c.stato.tipo === 'ollama' && !c.stato.raggiungibile && !c.stato.eseguibile) return 'Installa Ollama e scarica';
  return `Scarica e usa (${v.gb.toLocaleString('it-IT', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} GB)`;
}
