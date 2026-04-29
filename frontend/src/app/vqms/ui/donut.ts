import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

@Component({
  selector: 'vq-donut',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <svg [attr.width]="size()" [attr.height]="size()" viewBox="0 0 56 56">
      <circle cx="28" cy="28" [attr.r]="radius" fill="none" stroke="var(--line)" stroke-width="4" />
      <circle
        cx="28"
        cy="28"
        [attr.r]="radius"
        fill="none"
        [attr.stroke]="color()"
        stroke-width="4"
        [attr.stroke-dasharray]="dashArray()"
        stroke-linecap="round"
        transform="rotate(-90 28 28)"
      />
    </svg>
  `,
})
export class Donut {
  readonly pct = input.required<number>();
  readonly size = input<number>(56);

  protected readonly radius = 22;
  protected readonly circumference = 2 * Math.PI * 22;

  readonly dashArray = computed<string>(() => {
    const filled = (this.circumference * this.pct()) / 100;
    return `${filled} ${this.circumference}`;
  });

  readonly color = computed<string>(() => {
    const p = this.pct();
    if (p > 85) return 'var(--ok)';
    if (p > 70) return 'var(--warn)';
    return 'var(--bad)';
  });
}
