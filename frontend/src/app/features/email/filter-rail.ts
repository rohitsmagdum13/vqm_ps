import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { EmailsStore } from '../../data/emails.store';
import {
  MAIL_PRIORITIES,
  MAIL_SORT_FIELDS,
  MAIL_STATUSES,
  type MailPriority,
  type MailSortField,
  type MailSortOrder,
  type MailStatus,
} from '../../shared/models/email';

@Component({
  selector: 'app-filter-rail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <aside
      class="self-start rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-3 flex flex-col gap-4"
    >
      <div class="flex flex-col gap-1.5">
        <div class="text-[10px] font-mono uppercase tracking-wider text-fg-dim px-1">
          Status
        </div>
        <button
          type="button"
          (click)="setStatus(null)"
          [attr.aria-pressed]="status() === null"
          class="flex items-center justify-between rounded-[var(--radius-sm)] px-2 py-1 text-[13px] leading-5 transition text-left"
          [class]="rowClass(status() === null)"
        >
          <span class="truncate">All</span>
          <span class="ml-auto text-[11px] font-mono text-fg-dim">{{ counts().all }}</span>
        </button>
        @for (s of statuses; track s) {
          <button
            type="button"
            (click)="setStatus(s)"
            [attr.aria-pressed]="status() === s"
            class="flex items-center justify-between rounded-[var(--radius-sm)] px-2 py-1 text-[13px] leading-5 transition text-left"
            [class]="rowClass(status() === s)"
          >
            <span class="truncate">{{ s }}</span>
            <span class="ml-auto text-[11px] font-mono text-fg-dim">{{ statusCount(s) }}</span>
          </button>
        }
      </div>

      <div class="flex flex-col gap-1.5">
        <div class="text-[10px] font-mono uppercase tracking-wider text-fg-dim px-1">
          Priority
        </div>
        <button
          type="button"
          (click)="setPriority(null)"
          [attr.aria-pressed]="priority() === null"
          class="flex items-center gap-2 rounded-[var(--radius-sm)] px-2 py-1 text-[13px] leading-5 transition text-left"
          [class]="rowClass(priority() === null)"
        >
          <span
            class="h-2 w-2 rounded-full shrink-0 bg-fg-dim"
            aria-hidden="true"
          ></span>
          <span class="truncate">All</span>
        </button>
        @for (p of priorities; track p) {
          <button
            type="button"
            (click)="setPriority(p)"
            [attr.aria-pressed]="priority() === p"
            class="flex items-center gap-2 rounded-[var(--radius-sm)] px-2 py-1 text-[13px] leading-5 transition text-left"
            [class]="rowClass(priority() === p)"
          >
            <span
              class="h-2 w-2 rounded-full shrink-0"
              [class]="priorityDot(p)"
              aria-hidden="true"
            ></span>
            <span class="truncate">{{ p }}</span>
          </button>
        }
      </div>

      <div class="flex flex-col gap-1.5">
        <div class="text-[10px] font-mono uppercase tracking-wider text-fg-dim px-1">
          Sort
        </div>
        <label class="flex flex-col gap-1 px-1">
          <span class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">Field</span>
          <select
            class="rounded-[var(--radius-sm)] border border-border-light bg-surface-2 text-fg text-xs px-2 py-1.5 outline-none focus:border-primary"
            [value]="sortBy()"
            (change)="onSortFieldChange($event)"
          >
            @for (f of sortFields; track f) {
              <option [value]="f">{{ sortLabel(f) }}</option>
            }
          </select>
        </label>
        <button
          type="button"
          (click)="toggleSortOrder()"
          class="mx-1 mt-1 inline-flex items-center justify-between gap-2 rounded-[var(--radius-sm)] border border-border-light bg-surface-2 text-fg text-xs px-2 py-1.5 hover:bg-surface transition"
          [attr.aria-label]="'Toggle sort order, currently ' + sortOrder()"
        >
          <span class="truncate">{{ sortOrder() === 'asc' ? 'Ascending' : 'Descending' }}</span>
          <span aria-hidden="true">{{ sortOrder() === 'asc' ? '↑' : '↓' }}</span>
        </button>
      </div>
    </aside>
  `,
})
export class FilterRail {
  readonly #store = inject(EmailsStore);

  protected readonly statuses = MAIL_STATUSES;
  protected readonly priorities = MAIL_PRIORITIES;
  protected readonly sortFields = MAIL_SORT_FIELDS;

  protected readonly status = this.#store.status;
  protected readonly priority = this.#store.priority;
  protected readonly sortBy = this.#store.sortBy;
  protected readonly sortOrder = this.#store.sortOrder;
  protected readonly counts = this.#store.filterCounts;

  protected statusCount(s: MailStatus): number {
    const c = this.counts();
    if (s === 'New') return c.new;
    if (s === 'Reopened') return c.reopened;
    return c.resolved;
  }

  protected rowClass(active: boolean): string {
    return active
      ? 'bg-primary/10 text-primary font-semibold'
      : 'text-fg hover:bg-surface-2';
  }

  protected priorityDot(p: MailPriority): string {
    if (p === 'High') return 'bg-error';
    if (p === 'Medium') return 'bg-warn';
    return 'bg-info';
  }

  protected setStatus(s: MailStatus | null): void {
    this.#store.setStatus(s);
  }

  protected setPriority(p: MailPriority | null): void {
    this.#store.setPriority(p);
  }

  protected sortLabel(f: MailSortField): string {
    if (f === 'timestamp') return 'Timestamp';
    if (f === 'status') return 'Status';
    return 'Priority';
  }

  protected onSortFieldChange(ev: Event): void {
    const value = (ev.target as HTMLSelectElement).value as MailSortField;
    this.#store.setSort(value, this.sortOrder());
  }

  protected toggleSortOrder(): void {
    const next: MailSortOrder = this.sortOrder() === 'asc' ? 'desc' : 'asc';
    this.#store.setSort(this.sortBy(), next);
  }
}
