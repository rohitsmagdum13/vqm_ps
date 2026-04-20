import { Injectable, computed, signal } from '@angular/core';
import { PREF_TOGGLES } from '../features/preferences/preferences.data';

export type TogglesState = Readonly<Record<string, boolean>>;

function seedToggles(): TogglesState {
  const map: Record<string, boolean> = {};
  for (const t of PREF_TOGGLES) map[t.id] = t.defaultOn;
  return map;
}

@Injectable({ providedIn: 'root' })
export class PreferencesStore {
  readonly #toggles = signal<TogglesState>(seedToggles());
  readonly #lang = signal<string>('en');
  readonly #dirty = signal<boolean>(false);

  readonly toggles = this.#toggles.asReadonly();
  readonly lang = this.#lang.asReadonly();
  readonly dirty = this.#dirty.asReadonly();

  readonly isOn = (id: string) => computed(() => this.#toggles()[id] ?? false);

  setToggle(id: string, on: boolean): void {
    this.#toggles.update((s) => ({ ...s, [id]: on }));
    this.#dirty.set(true);
  }

  setLang(code: string): void {
    this.#lang.set(code);
    this.#dirty.set(true);
  }

  commit(): void {
    this.#dirty.set(false);
  }

  discard(): void {
    this.#toggles.set(seedToggles());
    this.#lang.set('en');
    this.#dirty.set(false);
  }
}
