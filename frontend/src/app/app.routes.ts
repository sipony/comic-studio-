import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'progetti' },
  { path: 'sistema', title: 'Sistema · Comic Studio', loadComponent: () => import('./pagine/sistema/sistema').then((m) => m.SistemaPage) },
  { path: 'progetti', title: 'Progetti · Comic Studio', loadComponent: () => import('./pagine/progetti/progetti').then((m) => m.ProgettiPage) },
  {
    path: 'progetto/:id',
    loadComponent: () => import('./pagine/progetto/progetto').then((m) => m.ProgettoPage),
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'personaggi' },
      {
        path: 'personaggi',
        title: 'Personaggi · Comic Studio',
        loadComponent: () => import('./pagine/personaggi/personaggi').then((m) => m.PersonaggiPage),
      },
      {
        path: 'dataset',
        title: 'Dataset · Comic Studio',
        loadComponent: () => import('./pagine/dataset/dataset').then((m) => m.DatasetPage),
      },
      {
        path: 'didascalie',
        title: 'Didascalie · Comic Studio',
        loadComponent: () => import('./pagine/didascalie/didascalie').then((m) => m.DidascaliePage),
      },
      {
        path: 'addestramento',
        title: 'Addestramento · Comic Studio',
        loadComponent: () => import('./pagine/addestramento/addestramento').then((m) => m.AddestramentoPage),
      },
      {
        path: ':passo',
        loadComponent: () => import('./pagine/in-arrivo/in-arrivo').then((m) => m.InArrivoPage),
      },
    ],
  },
  { path: '**', redirectTo: 'progetti' },
];
