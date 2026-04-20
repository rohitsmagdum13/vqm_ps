import { Injectable, signal } from '@angular/core';

export type ToastTone = 'info' | 'success' | 'warn' | 'error';

export interface ToastMsg {
  readonly id: number;
  readonly text: string;
  readonly tone: ToastTone;
}

@Injectable({ providedIn: 'root' })
export class ToastService {
  readonly #current = signal<ToastMsg | null>(null);
  readonly current = this.#current.asReadonly();
  #seq = 0;
  #timer: ReturnType<typeof setTimeout> | null = null;

  show(text: string, tone: ToastTone = 'info', durationMs = 3000): void {
    if (this.#timer !== null) {
      clearTimeout(this.#timer);
    }
    const id = ++this.#seq;
    this.#current.set({ id, text, tone });
    this.#timer = setTimeout(() => {
      if (this.#current()?.id === id) {
        this.#current.set(null);
      }
      this.#timer = null;
    }, durationMs);
  }

  dismiss(): void {
    if (this.#timer !== null) {
      clearTimeout(this.#timer);
      this.#timer = null;
    }
    this.#current.set(null);
  }
}
