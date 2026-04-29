import { Injectable, computed, signal } from '@angular/core';
import type { Query } from '../data/models';

@Injectable({ providedIn: 'root' })
export class DrawerService {
  readonly #openQuery = signal<Query | null>(null);
  readonly #paletteOpen = signal<boolean>(false);

  readonly openQuery = this.#openQuery.asReadonly();
  readonly paletteOpen = this.#paletteOpen.asReadonly();
  readonly anyOpen = computed<boolean>(() => this.#openQuery() !== null || this.#paletteOpen());

  showQuery(q: Query): void {
    this.#openQuery.set(q);
  }

  closeQuery(): void {
    this.#openQuery.set(null);
  }

  togglePalette(): void {
    this.#paletteOpen.set(!this.#paletteOpen());
  }

  showPalette(): void {
    this.#paletteOpen.set(true);
  }

  closePalette(): void {
    this.#paletteOpen.set(false);
  }
}
