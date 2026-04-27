import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export type KpiTone = 'ok' | 'warn' | 'error' | 'neutral';

@Component({
  selector: 'app-ops-kpi-tile',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <article
      class="rounded-[var(--radius-md)] bg-surface border shadow-sm p-4"
      [class]="containerClass()"
    >
      <header class="flex items-center justify-between gap-2">
        <span class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">
          {{ label() }}
        </span>
        <span class="text-base" aria-hidden="true">{{ icon() }}</span>
      </header>
      <div class="mt-2 flex items-baseline gap-2">
        <span class="text-2xl font-semibold tabular-nums" [class]="valueClass()">
          {{ value() }}
        </span>
        @if (unit(); as u) {
          <span class="text-xs text-fg-dim">{{ u }}</span>
        }
      </div>
      @if (sub(); as s) {
        <p class="mt-1 text-[11px] text-fg-dim">{{ s }}</p>
      }
    </article>
  `,
})
export class OpsKpiTile {
  readonly label = input.required<string>();
  readonly value = input.required<string>();
  readonly icon = input<string>('');
  readonly unit = input<string | null>(null);
  readonly sub = input<string | null>(null);
  readonly tone = input<KpiTone>('neutral');

  protected readonly containerClass = computed<string>(() => {
    switch (this.tone()) {
      case 'error':
        return 'border-error/30';
      case 'warn':
        return 'border-warn/30';
      case 'ok':
        return 'border-success/30';
      default:
        return 'border-border-light';
    }
  });

  protected readonly valueClass = computed<string>(() => {
    switch (this.tone()) {
      case 'error':
        return 'text-error';
      case 'warn':
        return 'text-warn';
      case 'ok':
        return 'text-success';
      default:
        return 'text-fg';
    }
  });
}
