import { ChangeDetectionStrategy, Component, input, model, output } from '@angular/core';
import type { Priority, QueryStatus } from '../../shared/models/query';

const STATUSES: readonly QueryStatus[] = ['Open', 'In Progress', 'Awaiting Vendor', 'Resolved', 'Breached'];
const PRIORITIES: readonly Priority[] = ['Critical', 'High', 'Medium', 'Low'];

@Component({
  selector: 'app-query-filters',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div
      class="flex flex-wrap items-center gap-2 rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-3"
    >
      <select
        [value]="status()"
        (change)="status.set(asStatus($any($event.target).value))"
        class="rounded-[var(--radius-sm)] bg-surface-2 border border-border-light text-xs font-medium text-fg px-2.5 py-1.5 focus:outline-none focus:border-primary"
      >
        <option value="">All Status</option>
        @for (s of statuses; track s) {
          <option [value]="s">{{ s }}</option>
        }
      </select>

      <select
        [value]="priority()"
        (change)="priority.set(asPriority($any($event.target).value))"
        class="rounded-[var(--radius-sm)] bg-surface-2 border border-border-light text-xs font-medium text-fg px-2.5 py-1.5 focus:outline-none focus:border-primary"
      >
        <option value="">All Priority</option>
        @for (p of priorities; track p) {
          <option [value]="p">{{ p }}</option>
        }
      </select>

      @if (status() !== '' || priority() !== '') {
        <button
          type="button"
          (click)="clear()"
          class="text-xs text-fg-dim hover:text-error transition"
        >Clear filters</button>
      }

      @if (canCreate()) {
        <button
          type="button"
          (click)="newQuery.emit()"
          class="ml-auto inline-flex items-center gap-2 rounded-[var(--radius-sm)] bg-primary text-surface text-xs font-medium px-3 py-1.5 hover:bg-secondary transition"
        >
          <span aria-hidden="true">＋</span> New Query
        </button>
      }
    </div>
  `,
})
export class QueryFilters {
  readonly status = model<QueryStatus | ''>('');
  readonly priority = model<Priority | ''>('');
  readonly canCreate = input<boolean>(true);
  readonly newQuery = output<void>();

  protected readonly statuses = STATUSES;
  protected readonly priorities = PRIORITIES;

  protected asStatus(v: string): QueryStatus | '' {
    return (STATUSES as readonly string[]).includes(v) ? (v as QueryStatus) : '';
  }
  protected asPriority(v: string): Priority | '' {
    return (PRIORITIES as readonly string[]).includes(v) ? (v as Priority) : '';
  }

  protected clear(): void {
    this.status.set('');
    this.priority.set('');
  }
}
