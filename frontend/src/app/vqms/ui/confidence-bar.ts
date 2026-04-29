import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

@Component({
  selector: 'vq-confidence-bar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="flex items-center gap-2">
      <div
        [style.width.px]="60"
        [style.height.px]="4"
        [style.background]="'var(--line)'"
        [style.border-radius.px]="2"
        [style.overflow]="'hidden'"
      >
        <div [style.width.%]="pct()" [style.height]="'100%'" [style.background]="fill()"></div>
      </div>
      <span class="mono" style="font-size: 11px; color: var(--ink-2); min-width: 32px;">{{
        value().toFixed(2)
      }}</span>
    </div>
  `,
})
export class ConfidenceBar {
  readonly value = input.required<number>();
  readonly threshold = input<number>(0.85);

  readonly pct = computed<number>(() => Math.round(this.value() * 100));
  readonly fill = computed<string>(() => {
    const v = this.value();
    if (v >= this.threshold()) return 'var(--ok)';
    if (v >= 0.6) return 'var(--warn)';
    return 'var(--bad)';
  });
}
