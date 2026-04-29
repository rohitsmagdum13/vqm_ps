import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export type TierName = 'PLATINUM' | 'GOLD' | 'SILVER' | 'BRONZE';

interface TierStyle {
  readonly bg: string;
  readonly fg: string;
  readonly label: string;
}

const TIERS: Record<TierName, TierStyle> = {
  PLATINUM: { bg: 'color-mix(in oklch, var(--ink) 92%, white)', fg: 'var(--bg)', label: 'PLATINUM' },
  GOLD: { bg: '#a16207', fg: 'white', label: 'GOLD' },
  SILVER: { bg: 'var(--line-strong)', fg: 'var(--ink)', label: 'SILVER' },
  BRONZE: { bg: '#9a3412', fg: 'white', label: 'BRONZE' },
};

@Component({
  selector: 'vq-tier',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span
      class="mono inline-flex items-center"
      [style.background]="style().bg"
      [style.color]="style().fg"
      style="font-size: 9.5px; padding: 1px 6px; border-radius: 2px; letter-spacing: .08em; font-weight: 600;"
      >{{ style().label }}</span
    >
  `,
})
export class Tier {
  readonly tier = input.required<TierName | string>();
  readonly style = computed<TierStyle>(
    () => TIERS[(this.tier() as TierName) ?? 'SILVER'] ?? TIERS.SILVER,
  );
}
