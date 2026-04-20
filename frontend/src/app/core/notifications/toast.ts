import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { ToastService, type ToastTone } from './toast.service';

@Component({
  selector: 'app-toast',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (msg(); as m) {
      <div
        role="status"
        aria-live="polite"
        class="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 rounded-[var(--radius-md)] shadow-lg border px-4 py-2.5 text-sm font-medium flex items-center gap-2"
        [class]="toneClass()"
        [style.animation]="'fade-up 0.25s ease-out'"
      >
        <span aria-hidden="true">{{ toneIcon() }}</span>
        <span>{{ m.text }}</span>
        <button
          type="button"
          class="ml-2 text-fg-dim hover:text-fg text-xs"
          (click)="dismiss()"
          aria-label="Dismiss"
        >✕</button>
      </div>
    }
  `,
})
export class ToastHost {
  readonly #service = inject(ToastService);
  protected readonly msg = this.#service.current;

  protected readonly toneClass = computed(() => {
    const m = this.msg();
    if (!m) return '';
    const map: Record<ToastTone, string> = {
      info: 'bg-surface border-info/30 text-fg',
      success: 'bg-surface border-success/30 text-fg',
      warn: 'bg-surface border-warn/30 text-fg',
      error: 'bg-surface border-error/30 text-fg',
    };
    return map[m.tone];
  });

  protected readonly toneIcon = computed(() => {
    const m = this.msg();
    if (!m) return '';
    const map: Record<ToastTone, string> = {
      info: 'ℹ️',
      success: '✅',
      warn: '⚠️',
      error: '⛔',
    };
    return map[m.tone];
  });

  protected dismiss(): void {
    this.#service.dismiss();
  }
}
