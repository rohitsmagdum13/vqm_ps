import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

const STYLES: Record<string, { fg: string; bg: string }> = {
  P1: { fg: 'var(--bad)', bg: 'color-mix(in oklch, var(--bad) 12%, var(--panel))' },
  P2: { fg: 'var(--warn)', bg: 'color-mix(in oklch, var(--warn) 12%, var(--panel))' },
  P3: { fg: 'var(--muted)', bg: 'var(--bg)' },
};

@Component({
  selector: 'vq-priority',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span
      class="mono"
      [style.background]="style().bg"
      [style.color]="style().fg"
      style="font-size: 10.5px; font-weight: 600; padding: 2px 6px; border-radius: 2px;"
      >{{ p() }}</span
    >
  `,
})
export class Priority {
  readonly p = input.required<string>();
  readonly style = computed(() => STYLES[this.p()] ?? STYLES['P3']!);
}
