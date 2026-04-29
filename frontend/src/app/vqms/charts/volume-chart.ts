import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export interface VolumeRow {
  readonly date: string;
  readonly A: number;
  readonly B: number;
  readonly C: number;
}

interface SeriesArea {
  readonly key: 'A' | 'B' | 'C';
  readonly color: string;
  readonly stroke: string;
  readonly fill: string;
}

const SERIES: readonly SeriesArea[] = [
  { key: 'A', color: 'var(--path-a)', stroke: 'var(--path-a)', fill: 'var(--path-a)' },
  { key: 'B', color: 'var(--path-b)', stroke: 'var(--path-b)', fill: 'var(--path-b)' },
  { key: 'C', color: 'var(--path-c)', stroke: 'var(--path-c)', fill: 'var(--path-c)' },
];

@Component({
  selector: 'vq-volume-chart',
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
      <defs>
        <linearGradient id="vqVolGA" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="var(--path-a)" stop-opacity="0.32" />
          <stop offset="100%" stop-color="var(--path-a)" stop-opacity="0" />
        </linearGradient>
        <linearGradient id="vqVolGB" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="var(--path-b)" stop-opacity="0.28" />
          <stop offset="100%" stop-color="var(--path-b)" stop-opacity="0" />
        </linearGradient>
        <linearGradient id="vqVolGC" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="var(--path-c)" stop-opacity="0.28" />
          <stop offset="100%" stop-color="var(--path-c)" stop-opacity="0" />
        </linearGradient>
      </defs>

      <!-- horizontal grid -->
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

      <!-- stacked areas -->
      @for (a of areas(); track a.key) {
        <path [attr.d]="a.fillD" [attr.fill]="'url(#vqVolG' + a.key + ')'" />
        <path [attr.d]="a.strokeD" [attr.stroke]="a.color" stroke-width="1.5" fill="none" />
      }

      <!-- x-axis labels -->
      @for (lbl of xLabels(); track $index) {
        <text
          [attr.x]="lbl.x"
          [attr.y]="height - 4"
          class="recharts-text mono"
          style="fill: var(--muted); font-size: 10px;"
          text-anchor="middle"
        >
          {{ lbl.text }}
        </text>
      }
    </svg>
  `,
})
export class VolumeChart {
  readonly data = input.required<readonly VolumeRow[]>();

  protected readonly width = 800;
  protected readonly height = 220;
  protected readonly padLeft = 30;
  protected readonly padRight = 8;
  protected readonly padTop = 8;
  protected readonly padBottom = 22;

  readonly maxStack = computed<number>(() => {
    const data = this.data();
    if (!data.length) return 1;
    return Math.max(...data.map((d) => d.A + d.B + d.C)) || 1;
  });

  readonly grids = computed<readonly number[]>(() => {
    const top = this.padTop;
    const bot = this.height - this.padBottom;
    const lines: number[] = [];
    for (let i = 0; i <= 4; i++) {
      lines.push(top + ((bot - top) * i) / 4);
    }
    return lines;
  });

  readonly areas = computed<readonly { key: 'A' | 'B' | 'C'; strokeD: string; fillD: string; color: string }[]>(() => {
    const data = this.data();
    if (!data.length) return [];
    const max = this.maxStack();
    const x0 = this.padLeft;
    const xN = this.width - this.padRight;
    const y0 = this.height - this.padBottom;
    const yT = this.padTop;
    const step = data.length > 1 ? (xN - x0) / (data.length - 1) : 0;

    const stacks: number[][] = data.map((d) => [d.A, d.A + d.B, d.A + d.B + d.C]);

    const yFor = (v: number): number => y0 - ((y0 - yT) * v) / max;

    const out: { key: 'A' | 'B' | 'C'; strokeD: string; fillD: string; color: string }[] = [];
    for (let s = 0; s < 3; s++) {
      const top = stacks.map((row, i) => ({ x: x0 + i * step, y: yFor(row[s]!) }));
      const bot = stacks.map((row, i) => ({
        x: x0 + i * step,
        y: s === 0 ? y0 : yFor(row[s - 1]!),
      }));
      const stroke = top.map((p, i) => (i === 0 ? `M${p.x},${p.y}` : `L${p.x},${p.y}`)).join(' ');
      const fill =
        stroke +
        ' ' +
        bot
          .slice()
          .reverse()
          .map((p) => `L${p.x},${p.y}`)
          .join(' ') +
        ' Z';
      out.push({ key: SERIES[s]!.key, strokeD: stroke, fillD: fill, color: SERIES[s]!.color });
    }
    return out;
  });

  readonly xLabels = computed<readonly { x: number; text: string }[]>(() => {
    const data = this.data();
    if (!data.length) return [];
    const x0 = this.padLeft;
    const xN = this.width - this.padRight;
    const step = data.length > 1 ? (xN - x0) / (data.length - 1) : 0;
    return data
      .map((d, i) => ({ x: x0 + i * step, text: d.date }))
      .filter((_, i) => i % 4 === 0);
  });
}
