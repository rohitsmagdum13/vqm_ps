import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { SparklineComponent, type SparkTone } from '../sparkline/sparkline';

export type KpiAccent = 'primary' | 'success' | 'warn' | 'info' | 'error';
export type TrendTone = 'up' | 'down' | 'flat';

@Component({
  selector: 'ui-kpi-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [SparklineComponent],
  template: `
    <button
      type="button"
      [disabled]="!clickable()"
      (click)="select.emit()"
      class="relative overflow-hidden rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm px-4 py-4 text-left w-full transition"
      [class.hover:border-primary]="clickable()"
      [class.hover:shadow-md]="clickable()"
      [class.hover:-translate-y-0.5]="clickable()"
      [class.cursor-default]="!clickable()"
    >
      <span class="absolute left-0 top-0 bottom-0 w-[3px]" [class]="accentClass()"></span>
      <div class="text-[9.5px] font-mono tracking-wider uppercase text-fg-dim mb-2">
        {{ label() }}
      </div>
      <div class="text-[26px] font-semibold font-mono text-fg leading-none">{{ value() }}</div>
      <div class="mt-2 flex items-center justify-between gap-3">
        <div class="text-[10px] font-mono" [class]="trendClass()">{{ trendText() }}</div>
        <div class="text-[10px] text-fg-dim">{{ subtext() }}</div>
      </div>
      @if (spark().length > 0) {
        <div class="mt-2">
          <ui-sparkline [data]="spark()" [tone]="sparkTone()" [ariaLabel]="label() + ' trend'" />
        </div>
      }
    </button>
  `,
})
export class KpiCardComponent {
  readonly label = input.required<string>();
  readonly value = input.required<string | number>();
  readonly accent = input<KpiAccent>('primary');
  readonly trend = input<TrendTone>('flat');
  readonly trendText = input<string>('');
  readonly subtext = input<string>('');
  readonly spark = input<readonly number[]>([]);
  readonly sparkTone = input<SparkTone>('primary');
  readonly clickable = input<boolean>(false);

  readonly select = output<void>();

  protected readonly accentClass = computed(() => {
    const map: Record<KpiAccent, string> = {
      primary: 'bg-primary',
      success: 'bg-success',
      warn: 'bg-warn',
      info: 'bg-info',
      error: 'bg-error',
    };
    return map[this.accent()];
  });

  protected readonly trendClass = computed(() => {
    const map: Record<TrendTone, string> = {
      up: 'text-success',
      down: 'text-success',
      flat: 'text-warn',
    };
    return map[this.trend()];
  });
}
