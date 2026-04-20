import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import type { AdminBreakdownRow, PriorityAccent } from './admin-dashboard.data';

@Component({
  selector: 'app-priority-breakdown',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <ul class="space-y-3">
      @for (row of rows(); track row.lbl) {
        <li class="flex items-start gap-3">
          <span class="mt-1 h-2 w-2 rounded-full shrink-0" [class]="dotClass(row.accent)"></span>
          <div class="flex-1 min-w-0">
            <div class="flex items-baseline justify-between gap-2">
              <span class="text-sm text-fg">{{ row.lbl }}</span>
              <span class="text-[11px] font-mono text-fg-dim">{{ row.n }} · {{ row.pct }}%</span>
            </div>
            <div class="mt-1 h-1.5 rounded-full bg-surface-2 overflow-hidden">
              <div class="h-full rounded-full" [class]="fillClass(row.accent)" [style.width.%]="row.pct"></div>
            </div>
          </div>
        </li>
      }
    </ul>
  `,
})
export class PriorityBreakdown {
  readonly rows = input.required<readonly AdminBreakdownRow[]>();

  protected dotClass(accent: PriorityAccent): string {
    const map: Record<PriorityAccent, string> = {
      error: 'bg-error',
      warn: 'bg-warn',
      primary: 'bg-primary',
      accent: 'bg-accent',
    };
    return map[accent];
  }

  protected fillClass(accent: PriorityAccent): string {
    return this.dotClass(accent);
  }
}
