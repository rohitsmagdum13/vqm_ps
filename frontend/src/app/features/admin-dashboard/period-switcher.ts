import { ChangeDetectionStrategy, Component, model } from '@angular/core';
import type { Period } from './admin-dashboard.data';

interface PeriodOption {
  readonly id: Period;
  readonly label: string;
}

const OPTIONS: readonly PeriodOption[] = [
  { id: 'daily', label: 'Daily' },
  { id: 'weekly', label: 'Weekly' },
  { id: 'monthly', label: 'Monthly' },
];

@Component({
  selector: 'app-period-switcher',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div
      class="inline-flex rounded-[var(--radius-sm)] bg-surface-2 border border-border-light p-0.5"
      role="tablist"
    >
      @for (o of options; track o.id) {
        <button
          type="button"
          role="tab"
          [attr.aria-selected]="period() === o.id"
          (click)="period.set(o.id)"
          class="px-3 py-1 text-xs font-medium rounded-[var(--radius-sm)] transition"
          [class]="period() === o.id ? 'bg-primary text-surface shadow-sm' : 'text-fg-dim hover:text-fg'"
        >
          {{ o.label }}
        </button>
      }
    </div>
  `,
})
export class PeriodSwitcher {
  readonly period = model.required<Period>();
  protected readonly options = OPTIONS;
}
