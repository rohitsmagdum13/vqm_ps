import { Injectable, effect, signal } from '@angular/core';

const STORAGE_KEY = 'vqms.design.theme';

@Injectable({ providedIn: 'root' })
export class ThemeService {
  readonly #dark = signal<boolean>(this.#load());
  readonly dark = this.#dark.asReadonly();

  constructor() {
    effect(() => {
      const isDark = this.#dark();
      try {
        document.documentElement.classList.toggle('dark', isDark);
        localStorage.setItem(STORAGE_KEY, isDark ? '1' : '0');
      } catch {
        // ignore
      }
    });
  }

  toggle(): void {
    this.#dark.set(!this.#dark());
  }

  set(dark: boolean): void {
    this.#dark.set(dark);
  }

  #load(): boolean {
    try {
      return localStorage.getItem(STORAGE_KEY) === '1';
    } catch {
      return false;
    }
  }
}
