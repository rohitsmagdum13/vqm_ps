import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export interface ConfidenceBand {
  readonly band: string;
  readonly n: number;
}

@Component({
  selector: 'vq-confidence-chart',
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
        <rect [attr.x]="b.x" [attr.y]="b.y" [attr.width]="barW()" [attr.height]="b.h" rx="2" [attr.fill]="b.fill" />
      }

      <!-- 0.85 reference line — between band 4 and 5 -->
      <line
        [attr.x1]="cutoffX()"
        [attr.x2]="cutoffX()"
        [attr.y1]="padTop"
        [attr.y2]="height - padBottom"
        stroke="var(--accent)"
        stroke-dasharray="3 3"
      />

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
export class ConfidenceChart {
  readonly data = input.required<readonly ConfidenceBand[]>();

  protected readonly width = 400;
  protected readonly height = 170;
  protected readonly padLeft = 28;
  protected readonly padRight = 8;
  protected readonly padTop = 8;
  protected readonly padBottom = 22;

  readonly maxV = computed<number>(() => {
    const d = this.data();
    if (!d.length) return 1;
    return Math.max(...d.map((r) => r.n)) || 1;
  });

  readonly slot = computed<number>(
    () => (this.width - this.padLeft - this.padRight) / Math.max(this.data().length, 1),
  );

  readonly barW = computed<number>(() => Math.max(8, this.slot() * 0.65));

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
    const slot = this.slot();
    const w = this.barW();
    return d.map((r, i) => {
      const x = x0 + i * slot + (slot - w) / 2;
      const h = ((y0 - yT) * r.n) / max;
      const fill = r.band.startsWith('0.8') || r.band.startsWith('0.9')
        ? 'var(--ok)'
        : r.band.startsWith('0.6')
          ? 'var(--warn)'
          : 'var(--bad)';
      return { x, y: y0 - h, h, fill };
    });
  });

  readonly cutoffX = computed<number>(() => {
    const d = this.data();
    if (!d.length) return 0;
    const idx = d.findIndex((b) => b.band.startsWith('0.8'));
    if (idx < 0) return 0;
    return this.padLeft + idx * this.slot();
  });

  readonly xLabels = computed(() => {
    const d = this.data();
    if (!d.length) return [];
    const x0 = this.padLeft;
    const slot = this.slot();
    return d.map((r, i) => ({ x: x0 + i * slot + slot / 2, text: r.band }));
  });
}
