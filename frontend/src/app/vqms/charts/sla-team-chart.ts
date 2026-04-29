import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export interface TeamSla {
  readonly team: string;
  readonly on_time: number;
  readonly breached: number;
}

interface Row {
  readonly team: string;
  readonly y: number;
  readonly okW: number;
  readonly badW: number;
  readonly badX: number;
}

@Component({
  selector: 'vq-sla-team-chart',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <svg
      width="100%"
      [attr.height]="height()"
      [attr.viewBox]="'0 0 ' + width + ' ' + height()"
      preserveAspectRatio="none"
      style="display:block;"
    >
      @for (g of grids(); track $index) {
        <line
          [attr.x1]="g"
          [attr.x2]="g"
          [attr.y1]="0"
          [attr.y2]="height() - padBottom"
          stroke="var(--line)"
          stroke-dasharray="2 4"
        />
      }

      @for (r of rows(); track r.team) {
        <text
          [attr.x]="0"
          [attr.y]="r.y + barH / 2 + 3"
          class="mono"
          style="fill: var(--muted); font-size: 10.5px;"
        >
          {{ r.team }}
        </text>
        <rect [attr.x]="padLeft" [attr.y]="r.y" [attr.width]="r.okW" [attr.height]="barH" rx="2" fill="var(--ok)" />
        <rect [attr.x]="r.badX" [attr.y]="r.y" [attr.width]="r.badW" [attr.height]="barH" rx="2" fill="var(--bad)" />
      }
    </svg>
  `,
})
export class SlaTeamChart {
  readonly data = input.required<readonly TeamSla[]>();

  protected readonly width = 380;
  protected readonly padLeft = 100;
  protected readonly padRight = 8;
  protected readonly padBottom = 4;
  protected readonly barH = 14;
  protected readonly rowGap = 8;

  readonly height = computed<number>(
    () => this.data().length * (this.barH + this.rowGap) + this.padBottom,
  );

  readonly maxV = computed<number>(() => {
    const d = this.data();
    if (!d.length) return 1;
    return Math.max(...d.map((r) => r.on_time + r.breached)) || 1;
  });

  readonly grids = computed<readonly number[]>(() => {
    const x0 = this.padLeft;
    const xN = this.width - this.padRight;
    return Array.from({ length: 5 }, (_, i) => x0 + ((xN - x0) * i) / 4);
  });

  readonly rows = computed<readonly Row[]>(() => {
    const max = this.maxV();
    const x0 = this.padLeft;
    const xN = this.width - this.padRight;
    const span = xN - x0;
    return this.data().map((r, i) => {
      const okW = (span * r.on_time) / max;
      const badW = (span * r.breached) / max;
      return {
        team: r.team,
        y: i * (this.barH + this.rowGap),
        okW,
        badW,
        badX: x0 + okW,
      };
    });
  });
}
