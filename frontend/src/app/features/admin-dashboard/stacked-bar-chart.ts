import { ChangeDetectionStrategy, Component, computed, input, signal } from '@angular/core';

interface BarSegments {
  readonly label: string;
  readonly resolved: number;
  readonly pending: number;
  readonly breached: number;
  readonly resolvedPct: number;
  readonly pendingPct: number;
  readonly breachedPct: number;
  readonly heightPct: number;
  readonly total: number;
}

@Component({
  selector: 'app-stacked-bar-chart',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div>
      <div class="flex items-end gap-1.5 h-40 border-b border-border-light pb-1">
        @for (b of bars(); track b.label; let i = $index) {
          <div
            class="flex-1 relative h-full flex items-end group focus:outline-none"
            tabindex="0"
            role="img"
            [attr.aria-label]="
              b.label + ': ' + b.resolved + ' resolved, ' + b.pending + ' pending, ' + b.breached + ' breached'
            "
            (mouseenter)="hovered.set(i)"
            (mouseleave)="onLeave(i)"
            (focus)="hovered.set(i)"
            (blur)="onLeave(i)"
          >
            <div
              class="w-full rounded-t-sm overflow-hidden flex flex-col-reverse transition-[filter,transform] duration-150 group-hover:brightness-110 group-focus:brightness-110 group-focus:ring-2 group-focus:ring-primary/40"
              [style.height.%]="b.heightPct"
            >
              <div class="bg-primary" [style.height.%]="b.resolvedPct"></div>
              <div class="bg-warn" [style.height.%]="b.pendingPct"></div>
              <div class="bg-error" [style.height.%]="b.breachedPct"></div>
            </div>

            @if (hovered() === i) {
              <div
                role="tooltip"
                class="pointer-events-none absolute left-1/2 -translate-x-1/2 bottom-full mb-2 z-10 min-w-[140px] rounded-[var(--radius-sm)] bg-fg text-surface text-[11px] shadow-lg px-3 py-2 space-y-1 whitespace-nowrap animate-[fade-up_0.15s_ease-out]"
              >
                <div class="font-semibold text-[11px] tracking-wide border-b border-surface/20 pb-1 mb-1">
                  {{ b.label }} · {{ b.total }} total
                </div>
                <div class="flex items-center justify-between gap-3">
                  <span class="flex items-center gap-1.5">
                    <span class="inline-block h-2 w-2 rounded-full bg-primary"></span>
                    Resolved
                  </span>
                  <span class="font-mono font-semibold">{{ b.resolved }}</span>
                </div>
                <div class="flex items-center justify-between gap-3">
                  <span class="flex items-center gap-1.5">
                    <span class="inline-block h-2 w-2 rounded-full bg-warn"></span>
                    Pending
                  </span>
                  <span class="font-mono font-semibold">{{ b.pending }}</span>
                </div>
                <div class="flex items-center justify-between gap-3">
                  <span class="flex items-center gap-1.5">
                    <span class="inline-block h-2 w-2 rounded-full bg-error"></span>
                    Breached
                  </span>
                  <span class="font-mono font-semibold">{{ b.breached }}</span>
                </div>
                <div
                  class="absolute left-1/2 -translate-x-1/2 top-full h-0 w-0 border-x-4 border-t-4 border-x-transparent"
                  style="border-top-color: var(--color-fg, #111);"
                  aria-hidden="true"
                ></div>
              </div>
            }
          </div>
        }
      </div>
      <div class="flex gap-1.5 mt-2">
        @for (b of bars(); track b.label) {
          <div class="flex-1 text-center text-[10px] font-mono text-fg-dim">{{ b.label }}</div>
        }
      </div>
    </div>
  `,
})
export class StackedBarChart {
  readonly labels = input.required<readonly string[]>();
  readonly resolved = input.required<readonly number[]>();
  readonly pending = input.required<readonly number[]>();
  readonly breached = input.required<readonly number[]>();

  protected readonly hovered = signal<number | null>(null);

  protected readonly bars = computed<readonly BarSegments[]>(() => {
    const labels = this.labels();
    const r = this.resolved();
    const p = this.pending();
    const b = this.breached();
    const totals = labels.map((_, i) => (r[i] ?? 0) + (p[i] ?? 0) + (b[i] ?? 0));
    const mx = Math.max(...totals, 1);
    return labels.map((label, i) => {
      const total = totals[i];
      const rr = r[i] ?? 0;
      const pp = p[i] ?? 0;
      const bb = b[i] ?? 0;
      const denom = total || 1;
      return {
        label,
        total,
        resolved: rr,
        pending: pp,
        breached: bb,
        heightPct: Math.round((total / mx) * 100),
        resolvedPct: Math.round((rr / denom) * 100),
        pendingPct: Math.round((pp / denom) * 100),
        breachedPct: Math.round((bb / denom) * 100),
      };
    });
  });

  protected onLeave(i: number): void {
    if (this.hovered() === i) this.hovered.set(null);
  }
}
