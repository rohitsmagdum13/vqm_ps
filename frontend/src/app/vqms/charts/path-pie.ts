import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

interface Slice {
  readonly name: string;
  readonly value: number;
  readonly color: string;
  readonly d: string;
  readonly pct: number;
}

@Component({
  selector: 'vq-path-pie',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="flex items-center gap-4">
      <div [style.width.px]="110" [style.height.px]="110">
        <svg width="110" height="110" viewBox="0 0 110 110">
          @for (s of slices(); track s.name) {
            <path [attr.d]="s.d" [attr.fill]="s.color" stroke="var(--panel)" stroke-width="2" />
          }
          <circle cx="55" cy="55" [attr.r]="36" fill="var(--panel)" />
        </svg>
      </div>
      <div class="flex flex-col gap-1.5 text-[12px]">
        @for (s of slices(); track s.name) {
          <div class="flex items-center gap-2">
            <span [style.width.px]="8" [style.height.px]="8" [style.background]="s.color" [style.border-radius.px]="2"></span>
            <span class="ink-2" [style.min-width.px]="56">{{ s.name }}</span>
            <span class="mono ink" style="font-weight:600">{{ s.pct }}%</span>
            <span class="mono muted">({{ s.value }})</span>
          </div>
        }
      </div>
    </div>
  `,
})
export class PathPie {
  readonly a = input.required<number>();
  readonly b = input.required<number>();
  readonly c = input.required<number>();

  readonly total = computed<number>(() => Math.max(this.a() + this.b() + this.c(), 1));

  readonly slices = computed<readonly Slice[]>(() => {
    const total = this.total();
    const cx = 55;
    const cy = 55;
    const rOuter = 52;
    const data = [
      { name: 'Path A', value: this.a(), color: 'var(--path-a)' },
      { name: 'Path B', value: this.b(), color: 'var(--path-b)' },
      { name: 'Path C', value: this.c(), color: 'var(--path-c)' },
    ];
    let cursor = -Math.PI / 2;
    return data.map((d) => {
      const angle = (d.value / total) * Math.PI * 2;
      const start = cursor;
      const end = cursor + angle;
      cursor = end;
      const large = angle > Math.PI ? 1 : 0;
      const sx = cx + rOuter * Math.cos(start);
      const sy = cy + rOuter * Math.sin(start);
      const ex = cx + rOuter * Math.cos(end);
      const ey = cy + rOuter * Math.sin(end);
      const path = `M${cx},${cy} L${sx.toFixed(2)},${sy.toFixed(2)} A${rOuter},${rOuter} 0 ${large} 1 ${ex.toFixed(2)},${ey.toFixed(2)} Z`;
      return {
        name: d.name,
        value: d.value,
        color: d.color,
        d: path,
        pct: Math.round((d.value / total) * 100),
      };
    });
  });
}
