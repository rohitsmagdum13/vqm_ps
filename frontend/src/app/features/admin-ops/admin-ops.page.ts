import { ChangeDetectionStrategy, Component, computed } from '@angular/core';
import { DatePipe } from '@angular/common';
import { SYSTEM_SNAPSHOT } from '../../data/ops.seed';
import type { ServiceStatus } from '../../shared/models/ops';
import { OpsCopilotPanel } from './ops-copilot-panel';
import { OpsKpiTile } from './ops-kpi-tile';

function statusColor(s: ServiceStatus): string {
  switch (s) {
    case 'healthy':
      return 'bg-success';
    case 'degraded':
      return 'bg-warn';
    case 'down':
      return 'bg-error';
  }
}

@Component({
  selector: 'app-admin-ops-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, OpsCopilotPanel, OpsKpiTile],
  template: `
    <section class="space-y-6 animate-[fade-up_0.3s_ease-out]">
      <header
        class="flex items-start justify-between gap-3 flex-wrap rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-5"
      >
        <div class="flex items-start gap-3 min-w-0 flex-1">
          <div
            class="h-10 w-10 shrink-0 rounded-full bg-primary/10 text-primary flex items-center justify-center text-lg"
          >🛠</div>
          <div class="min-w-0">
            <h1 class="text-xl font-semibold text-fg tracking-tight">Ops Console</h1>
            <p class="mt-1 text-xs text-fg-dim">
              Read-only system status + AI copilot. Snapshot taken {{ snapshot.timestamp_ist | date: 'MMM d, h:mm a' }}.
            </p>
          </div>
        </div>
        <div class="flex items-center gap-2 text-[11px] text-fg-dim">
          <span class="h-2 w-2 rounded-full bg-success inline-block"></span>
          <span>Live · refreshes every 30s in production</span>
        </div>
      </header>

      <div class="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <app-ops-kpi-tile
          label="DLQ depth"
          icon="📦"
          [value]="dlqTotal().toString()"
          [tone]="dlqTotal() > 0 ? 'warn' : 'ok'"
          [sub]="dlqTotal() > 0 ? 'Investigate vqms-analysis-dlq' : 'All queues empty'"
        />
        <app-ops-kpi-tile
          label="SLA breaches"
          icon="⏱"
          [value]="snapshot.sla.breached.toString()"
          [unit]="'/ ' + snapshot.sla.total"
          [tone]="snapshot.sla.breached > 0 ? 'error' : 'ok'"
          sub="last 24h"
        />
        <app-ops-kpi-tile
          label="Queries today"
          icon="📋"
          [value]="snapshot.queries_today.received.toString()"
          [tone]="'neutral'"
          [sub]="snapshot.queries_today.resolved + ' resolved · ' + snapshot.queries_today.in_progress + ' in progress'"
        />
        <app-ops-kpi-tile
          label="LLM cost today"
          icon="💸"
          [value]="costLabel()"
          [tone]="snapshot.cost.today_usd > snapshot.cost.yesterday_usd ? 'warn' : 'ok'"
          [sub]="'avg $' + snapshot.cost.avg_per_query_usd.toFixed(3) + '/query'"
        />
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div class="lg:col-span-2 space-y-6">
          <article
            class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-5"
          >
            <h2 class="text-sm font-semibold text-fg mb-3">Pipeline health</h2>
            <ul class="space-y-2">
              @for (svc of snapshot.pipeline_health; track svc.name) {
                <li class="flex items-center justify-between gap-3 py-1.5 border-b border-border-light last:border-0">
                  <div class="flex items-center gap-2.5 min-w-0">
                    <span class="h-2 w-2 rounded-full inline-block" [class]="statusColor(svc.status)" aria-hidden="true"></span>
                    <span class="text-sm text-fg">{{ svc.name }}</span>
                    @if (svc.note) {
                      <span class="text-[11px] text-fg-dim truncate" [title]="svc.note">— {{ svc.note }}</span>
                    }
                  </div>
                  <div class="flex items-center gap-3 text-[11px] font-mono text-fg-dim shrink-0">
                    <span>p99 {{ svc.latency_p99_ms }}ms</span>
                    <span
                      class="inline-flex items-center rounded-full px-2 py-0.5 font-semibold"
                      [class]="svc.status === 'healthy'
                        ? 'bg-success/15 text-success'
                        : svc.status === 'degraded'
                        ? 'bg-warn/15 text-warn'
                        : 'bg-error/15 text-error'"
                    >{{ svc.status }}</span>
                  </div>
                </li>
              }
            </ul>
          </article>

          <article
            class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-5"
          >
            <h2 class="text-sm font-semibold text-fg mb-3">Path distribution today</h2>
            <div class="flex items-center gap-2 text-xs">
              <div class="h-3 rounded-full overflow-hidden flex-1 bg-surface-2 flex">
                <div class="bg-success h-full" [style.width.%]="pathPct().a"></div>
                <div class="bg-primary h-full" [style.width.%]="pathPct().b"></div>
                <div class="bg-warn h-full" [style.width.%]="pathPct().c"></div>
              </div>
              <span class="text-fg-dim font-mono shrink-0">{{ pathTotal() }} total</span>
            </div>
            <ul class="mt-3 grid grid-cols-3 gap-3 text-xs">
              <li>
                <div class="flex items-center gap-1.5">
                  <span class="h-2 w-2 rounded-full bg-success inline-block"></span>
                  <span class="text-fg">Path A · AI-resolved</span>
                </div>
                <div class="mt-1 text-fg font-semibold">{{ snapshot.path_distribution_today.A }}</div>
                <div class="text-fg-dim text-[11px]">{{ pathPct().a }}%</div>
              </li>
              <li>
                <div class="flex items-center gap-1.5">
                  <span class="h-2 w-2 rounded-full bg-primary inline-block"></span>
                  <span class="text-fg">Path B · team</span>
                </div>
                <div class="mt-1 text-fg font-semibold">{{ snapshot.path_distribution_today.B }}</div>
                <div class="text-fg-dim text-[11px]">{{ pathPct().b }}%</div>
              </li>
              <li>
                <div class="flex items-center gap-1.5">
                  <span class="h-2 w-2 rounded-full bg-warn inline-block"></span>
                  <span class="text-fg">Path C · review</span>
                </div>
                <div class="mt-1 text-fg font-semibold">{{ snapshot.path_distribution_today.C }}</div>
                <div class="text-fg-dim text-[11px]">{{ pathPct().c }}%</div>
              </li>
            </ul>
          </article>

          @if (snapshot.stuck_queries.length > 0) {
            <article
              class="rounded-[var(--radius-md)] bg-error/5 border border-error/30 shadow-sm p-5"
            >
              <h2 class="text-sm font-semibold text-error mb-3 flex items-center gap-2">
                <span aria-hidden="true">⚠</span>
                <span>Stuck queries</span>
              </h2>
              <ul class="space-y-1.5 text-xs">
                @for (s of snapshot.stuck_queries; track s.query_id) {
                  <li class="flex items-center justify-between gap-3">
                    <div class="min-w-0">
                      <span class="font-mono text-fg">{{ s.query_id }}</span>
                      <span class="text-fg-dim ml-2">{{ s.vendor }}</span>
                    </div>
                    <div class="text-fg-dim font-mono shrink-0">
                      {{ s.stuck_at_node }} · {{ s.stuck_for_min }}min
                    </div>
                  </li>
                }
              </ul>
            </article>
          }
        </div>

        <div class="lg:col-span-1">
          <app-ops-copilot-panel />
        </div>
      </div>
    </section>
  `,
})
export class AdminOpsPage {
  protected readonly snapshot = SYSTEM_SNAPSHOT;
  protected readonly statusColor = statusColor;

  protected readonly dlqTotal = computed<number>(() =>
    this.snapshot.dlq.reduce((sum, q) => sum + q.depth, 0),
  );

  protected readonly costLabel = computed<string>(() => `$${this.snapshot.cost.today_usd.toFixed(2)}`);

  protected readonly pathTotal = computed<number>(() => {
    const p = this.snapshot.path_distribution_today;
    return p.A + p.B + p.C;
  });

  protected readonly pathPct = computed<{ a: number; b: number; c: number }>(() => {
    const p = this.snapshot.path_distribution_today;
    const total = p.A + p.B + p.C;
    if (total === 0) return { a: 0, b: 0, c: 0 };
    return {
      a: Math.round((p.A / total) * 100),
      b: Math.round((p.B / total) * 100),
      c: Math.round((p.C / total) * 100),
    };
  });
}
