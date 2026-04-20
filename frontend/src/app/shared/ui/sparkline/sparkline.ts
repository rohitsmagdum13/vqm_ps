import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export type SparkTone = 'primary' | 'success' | 'warn' | 'info' | 'error' | 'accent';

@Component({
  selector: 'ui-sparkline',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span
      class="inline-flex items-end gap-[2px] h-[18px]"
      [attr.aria-label]="ariaLabel()"
      role="img"
    >
      @for (bar of bars(); track $index) {
        <span
          class="w-[3px] rounded-sm opacity-70"
          [class]="barClass()"
          [style.height.px]="bar"
        ></span>
      }
    </span>
  `,
})
export class SparklineComponent {
  readonly data = input.required<readonly number[]>();
  readonly tone = input<SparkTone>('primary');
  readonly ariaLabel = input<string>('trend');

  protected readonly bars = computed<readonly number[]>(() => {
    const d = this.data();
    if (d.length === 0) return [];
    const mx = Math.max(...d);
    if (mx <= 0) return d.map(() => 1);
    return d.map((v) => Math.max(1, Math.round((v / mx) * 18)));
  });

  protected readonly barClass = computed(() => {
    const map: Record<SparkTone, string> = {
      primary: 'bg-primary',
      success: 'bg-success',
      warn: 'bg-warn',
      info: 'bg-info',
      error: 'bg-error',
      accent: 'bg-accent',
    };
    return map[this.tone()];
  });
}
