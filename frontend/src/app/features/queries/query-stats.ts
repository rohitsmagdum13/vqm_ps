import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import type { QueryStats } from '../../data/queries.store';

interface StatTile {
  readonly label: string;
  readonly value: number;
  readonly accent: 'info' | 'primary' | 'warn' | 'success' | 'error';
}

@Component({
  selector: 'app-query-stats',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-8">
      @for (t of tiles(); track t.label) {
        <div
          class="relative rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm px-4 py-3 text-center overflow-hidden"
        >
          <span class="absolute left-0 top-0 bottom-0 w-[3px]" [class]="accentClass(t.accent)"></span>
          <div class="text-2xl font-mono font-semibold leading-none" [class]="textClass(t.accent)">
            {{ t.value }}
          </div>
          <div class="mt-1 text-[10px] font-mono tracking-wider uppercase text-fg-dim">
            {{ t.label }}
          </div>
        </div>
      }
    </div>
  `,
})
export class QueryStatsComponent {
  readonly stats = input.required<QueryStats>();

  protected readonly tiles = computed<readonly StatTile[]>(() => {
    const s = this.stats();
    return [
      { label: 'Open', value: s.open, accent: 'info' },
      { label: 'In Prog', value: s.inProgress, accent: 'primary' },
      { label: 'Awaiting', value: s.awaiting, accent: 'warn' },
      { label: 'Resolved', value: s.resolved, accent: 'success' },
      { label: 'Breached', value: s.breached, accent: 'error' },
    ];
  });

  protected accentClass(a: StatTile['accent']): string {
    const map = {
      info: 'bg-info',
      primary: 'bg-primary',
      warn: 'bg-warn',
      success: 'bg-success',
      error: 'bg-error',
    } as const;
    return map[a];
  }

  protected textClass(a: StatTile['accent']): string {
    const map = {
      info: 'text-info',
      primary: 'text-primary',
      warn: 'text-warn',
      success: 'text-success',
      error: 'text-error',
    } as const;
    return map[a];
  }
}
