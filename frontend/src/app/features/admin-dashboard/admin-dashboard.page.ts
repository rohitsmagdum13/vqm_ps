import { ChangeDetectionStrategy, Component, computed, signal } from '@angular/core';
import { AD_DATA, type Period } from './admin-dashboard.data';
import { PeriodSwitcher } from './period-switcher';
import { AdminKpiGrid } from './admin-kpi-grid';
import { StackedBarChart } from './stacked-bar-chart';
import { PriorityBreakdown } from './priority-breakdown';
import { AdminAlerts } from './admin-alerts';

@Component({
  selector: 'app-admin-dashboard-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    PeriodSwitcher,
    AdminKpiGrid,
    StackedBarChart,
    PriorityBreakdown,
    AdminAlerts,
  ],
  template: `
    <section class="space-y-8 animate-[fade-up_0.3s_ease-out]">
      <header
        class="flex items-start justify-between gap-4 flex-wrap rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-5"
      >
        <div class="flex items-start gap-3">
          <div
            class="h-10 w-10 shrink-0 rounded-full bg-primary/10 text-primary flex items-center justify-center text-lg"
          >
            📊
          </div>
          <div>
            <h1 class="text-xl font-semibold text-fg tracking-tight">Operations Dashboard</h1>
            <p class="mt-1 text-xs text-fg-dim">{{ data().sub }}</p>
          </div>
        </div>
        <app-period-switcher [(period)]="period" />
      </header>

      <app-admin-kpi-grid [kpis]="data().kpis" />

      <div class="grid grid-cols-1 lg:grid-cols-3 gap-10">
        <article
          class="lg:col-span-2 rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-5 space-y-4"
        >
          <div class="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <h2 class="text-sm font-semibold text-fg">Queries resolved over time</h2>
              <p class="mt-0.5 text-[11px] text-fg-dim">{{ data().chartSub }}</p>
            </div>
            <ul class="flex flex-wrap gap-3 text-[11px] text-fg-dim">
              <li class="flex items-center gap-1.5">
                <span class="inline-block h-2 w-2 rounded-full bg-primary"></span>Resolved
              </li>
              <li class="flex items-center gap-1.5">
                <span class="inline-block h-2 w-2 rounded-full bg-warn"></span>Pending
              </li>
              <li class="flex items-center gap-1.5">
                <span class="inline-block h-2 w-2 rounded-full bg-error"></span>Breached
              </li>
            </ul>
          </div>
          <app-stacked-bar-chart
            [labels]="data().labels"
            [resolved]="data().resolved"
            [pending]="data().pending"
            [breached]="data().breached"
          />
        </article>

        <article
          class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-5 space-y-4"
        >
          <div>
            <h2 class="text-sm font-semibold text-fg">Priority breakdown</h2>
            <p class="mt-0.5 text-[11px] text-fg-dim">By severity this period</p>
          </div>
          <app-priority-breakdown [rows]="data().breakdown" />
        </article>
      </div>

      <article
        class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-5 space-y-4"
      >
        <div>
          <h2 class="text-sm font-semibold text-fg">Attention needed</h2>
          <p class="mt-0.5 text-[11px] text-fg-dim">High-priority alerts</p>
        </div>
        <app-admin-alerts [alerts]="data().alerts" />
      </article>
    </section>
  `,
})
export class AdminDashboardPage {
  protected readonly period = signal<Period>('daily');
  protected readonly data = computed(() => AD_DATA[this.period()]);
}
