import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { Icon } from './icon';
import { Sparkline } from './sparkline';

@Component({
  selector: 'vq-kpi',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Icon, Sparkline],
  template: `
    <div class="panel p-4 fade-up" style="border-radius:4px;">
      <div class="flex items-start justify-between mb-3">
        <div
          class="text-[10.5px] muted uppercase font-medium"
          style="letter-spacing: .04em;"
        >
          {{ label() }}
        </div>
        @if (icon()) {
          <vq-icon [name]="icon()!" [size]="14" cssClass="muted" />
        }
      </div>
      <div class="flex items-baseline gap-2">
        <div
          class="ink"
          style="font-size: 28px; font-weight: 600; letter-spacing: -.02em; line-height: 1;"
        >
          {{ value() }}
        </div>
        @if (delta() !== null && delta() !== undefined) {
          <span
            class="mono"
            style="font-size: 11px; font-weight: 600;"
            [style.color]="delta()! >= 0 ? 'var(--ok)' : 'var(--bad)'"
          >
            {{ delta()! >= 0 ? '▲' : '▼' }} {{ absDelta() }}%
          </span>
        }
      </div>
      @if (sub()) {
        <div class="muted mt-1.5" style="font-size: 11.5px;">{{ sub() }}</div>
      }
      @if (sparkline() && sparkline()!.length > 0) {
        <div class="mt-3 -mx-1">
          <vq-sparkline [data]="sparkline()!" [color]="sparkColor()" />
        </div>
      }
    </div>
  `,
})
export class Kpi {
  readonly label = input.required<string>();
  readonly value = input.required<string | number>();
  readonly delta = input<number | null>(null);
  readonly sub = input<string>('');
  readonly icon = input<string | null>(null);
  readonly sparkline = input<readonly number[] | null>(null);
  readonly sparkColor = input<string>('var(--accent)');

  protected absDelta(): number {
    const d = this.delta();
    return d === null || d === undefined ? 0 : Math.abs(d);
  }
}
