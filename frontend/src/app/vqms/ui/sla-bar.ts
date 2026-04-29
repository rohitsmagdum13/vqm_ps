import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

@Component({
  selector: 'vq-sla-bar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (pct() == null) {
      <span class="subtle mono text-xs">—</span>
    } @else {
      <div class="flex items-center gap-2">
        <div
          [style.width.px]="56"
          [style.height.px]="4"
          [style.background]="'var(--line)'"
          [style.border-radius.px]="2"
          [style.overflow]="'hidden'"
        >
          <div [style.width.%]="pct()!" [style.height]="'100%'" [style.background]="color()"></div>
        </div>
        <span class="mono" style="font-size: 11px; color: var(--ink-2);">{{ pct() }}%</span>
      </div>
    }
  `,
})
export class SlaBar {
  readonly pct = input<number | null | undefined>(null);

  readonly color = computed<string>(() => {
    const p = this.pct() ?? 0;
    if (p >= 95) return 'var(--bad)';
    if (p >= 70) return 'var(--warn)';
    return 'var(--ok)';
  });
}
