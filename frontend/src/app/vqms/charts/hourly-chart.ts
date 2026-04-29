import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export interface HourlyRow {
  readonly hour: string;
  readonly ingested: number;
  readonly resolved: number;
}

@Component({
  selector: 'vq-hourly-chart',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <svg
      width="100%"
      [attr.height]="height"
      [attr.viewBox]="'0 0 ' + width + ' ' + height"
      preserveAspectRatio="none"
      style="display:block;"
    >
      @for (g of grids(); track $index) {
        <line
          [attr.x1]="padLeft"
          [attr.x2]="width - padRight"
          [attr.y1]="g"
          [attr.y2]="g"
          stroke="var(--line)"
          stroke-dasharray="2 4"
        />
      }

      @for (b of bars(); track $index) {
        <rect [attr.x]="b.x" [attr.y]="b.yI" [attr.width]="barW" [attr.height]="b.hI" rx="2" fill="var(--ink-2)" />
        <rect [attr.x]="b.x + barW + 2" [attr.y]="b.yR" [attr.width]="barW" [attr.height]="b.hR" rx="2" fill="var(--accent)" />
      }

      @for (lbl of xLabels(); track $index) {
        <text
          [attr.x]="lbl.x"
          [attr.y]="height - 4"
          class="mono"
          style="fill: var(--muted); font-size: 10px;"
          text-anchor="middle"
        >
          {{ lbl.text }}
        </text>
      }
    </svg>
  `,
})
export class HourlyChart {
  readonly data = input.required<readonly HourlyRow[]>();

  protected readonly width = 600;
  protected readonly height = 180;
  protected readonly padLeft = 28;
  protected readonly padRight = 8;
  protected readonly padTop = 8;
  protected readonly padBottom = 22;
  protected readonly barW = 8;

  readonly maxV = computed<number>(() => {
    const d = this.data();
    if (!d.length) return 1;
    return Math.max(...d.map((r) => Math.max(r.ingested, r.resolved))) || 1;
  });

  readonly grids = computed<readonly number[]>(() => {
    const t = this.padTop;
    const b = this.height - this.padBottom;
    return Array.from({ length: 5 }, (_, i) => t + ((b - t) * i) / 4);
  });

  readonly bars = computed(() => {
    const d = this.data();
    if (!d.length) return [];
    const max = this.maxV();
    const x0 = this.padLeft;
    const y0 = this.height - this.padBottom;
    const yT = this.padTop;
    const slot = (this.width - this.padLeft - this.padRight) / Math.max(d.length, 1);
    return d.map((r, i) => {
      const x = x0 + i * slot;
      const hI = ((y0 - yT) * r.ingested) / max;
      const hR = ((y0 - yT) * r.resolved) / max;
      return {
        x,
        yI: y0 - hI,
        hI,
        yR: y0 - hR,
        hR,
      };
    });
  });

  readonly xLabels = computed(() => {
    const d = this.data();
    if (!d.length) return [];
    const x0 = this.padLeft;
    const slot = (this.width - this.padLeft - this.padRight) / Math.max(d.length, 1);
    return d
      .map((r, i) => ({ x: x0 + i * slot + this.barW + 1, text: r.hour }))
      .filter((_, i) => i % 3 === 0);
  });
}
