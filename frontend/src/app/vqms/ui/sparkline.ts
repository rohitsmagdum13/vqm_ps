import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

@Component({
  selector: 'vq-sparkline',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <svg
      [attr.height]="height()"
      width="100%"
      preserveAspectRatio="none"
      [attr.viewBox]="viewBox()"
      style="display:block;"
    >
      <defs>
        <linearGradient [attr.id]="gradId" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" [attr.stop-color]="color()" stop-opacity="0.28" />
          <stop offset="100%" [attr.stop-color]="color()" stop-opacity="0" />
        </linearGradient>
      </defs>
      <path [attr.d]="fillPath()" [attr.fill]="'url(#' + gradId + ')'" />
      <path [attr.d]="strokePath()" [attr.stroke]="color()" stroke-width="1.5" fill="none" />
    </svg>
  `,
})
export class Sparkline {
  private static idCounter = 0;
  protected readonly gradId = `vq-spark-${++Sparkline.idCounter}`;

  readonly data = input.required<readonly number[]>();
  readonly height = input<number>(28);
  readonly color = input<string>('var(--accent)');

  readonly viewBox = computed<string>(() => `0 0 100 ${this.height()}`);

  readonly strokePath = computed<string>(() => {
    const data = this.data();
    if (!data.length) return '';
    const h = this.height();
    const min = Math.min(...data);
    const max = Math.max(...data);
    const range = max - min || 1;
    const step = data.length > 1 ? 100 / (data.length - 1) : 0;
    const points = data.map((v, i) => {
      const x = i * step;
      const y = h - ((v - min) / range) * (h - 4) - 2;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    });
    return 'M' + points.join(' L');
  });

  readonly fillPath = computed<string>(() => {
    const stroke = this.strokePath();
    if (!stroke) return '';
    const h = this.height();
    return `${stroke} L100,${h} L0,${h} Z`;
  });
}
