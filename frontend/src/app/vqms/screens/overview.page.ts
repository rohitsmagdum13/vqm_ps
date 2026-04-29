import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Icon } from '../ui/icon';
import { Mono } from '../ui/mono';
import { Tier } from '../ui/tier';
import { Status } from '../ui/status';
import { Priority } from '../ui/priority';
import { PathBadge } from '../ui/path-badge';
import { ConfidenceBar } from '../ui/confidence-bar';
import { SlaBar } from '../ui/sla-bar';
import { SectionHead } from '../ui/section-head';
import { Kpi } from '../ui/kpi';
import { EndpointsButton } from '../ui/endpoints-button';
import { EndpointsDrawer } from '../ui/endpoints-drawer';
import { VolumeChart } from '../charts/volume-chart';
import { HourlyChart } from '../charts/hourly-chart';
import { ConfidenceChart } from '../charts/confidence-chart';
import { PathPie } from '../charts/path-pie';
import { SlaTeamChart } from '../charts/sla-team-chart';
import {
  CONFIDENCE_HIST,
  HOURLY_24H,
  SLA_BY_TEAM,
  TOP_INTENTS,
  TREND_30D,
  relativeTime,
} from '../data/mock-data';
import { ENDPOINTS_OVERVIEW } from '../data/endpoints';
import { DrawerService } from '../services/drawer.service';
import { QueriesStore } from '../services/queries.store';
import { RoleService } from '../services/role.service';
import { VendorsStore } from '../services/vendors.store';

@Component({
  selector: 'vq-overview-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    Icon,
    Mono,
    Tier,
    Status,
    Priority,
    PathBadge,
    ConfidenceBar,
    SlaBar,
    SectionHead,
    Kpi,
    EndpointsButton,
    EndpointsDrawer,
    VolumeChart,
    HourlyChart,
    ConfidenceChart,
    PathPie,
    SlaTeamChart,
  ],
  template: `
    <div class="p-6 max-w-[1600px] mx-auto fade-up">
      <div class="flex items-center justify-between mb-5">
        <div>
          <div class="ink" style="font-size:22px; font-weight:600; letter-spacing:-.02em;">
            Operations overview
          </div>
          <div class="muted mt-1" style="font-size:13px;">
            <span class="mono">{{ today }}</span> · Last 30 days · All vendors
          </div>
        </div>
        <div class="flex items-center gap-2">
          <button class="btn"><vq-icon name="calendar" [size]="13" /> Last 30 days</button>
          <button class="btn"><vq-icon name="download" [size]="13" /> Export</button>
          <button class="btn btn-primary"><vq-icon name="bell" [size]="13" /> Subscribe</button>
          <vq-endpoints-button (clicked)="endpointsOpen.set(true)" />
        </div>
      </div>

      <vq-endpoints-drawer
        [open]="endpointsOpen()"
        title="Operations overview · backend contract"
        subtitle="src/api/routes/dashboard.py"
        [endpoints]="endpoints"
        [role]="role.role()"
        (closed)="endpointsOpen.set(false)"
      />

      <!-- KPI row -->
      <div class="grid grid-cols-4 gap-3 mb-3">
        <vq-kpi
          label="Queries received"
          value="1,284"
          [delta]="12"
          sub="vs. previous 30d · 42.8/day avg"
          icon="inbox"
          [sparkline]="sparkReceived()"
          sparkColor="var(--ink-2)"
        />
        <vq-kpi
          label="Resolution rate"
          value="91.4%"
          [delta]="2"
          sub="1,174 of 1,284 · auto‑close enabled"
          icon="check-circle"
          [sparkline]="sparkSla()"
          sparkColor="var(--ok)"
        />
        <vq-kpi
          label="Avg response time"
          value="4h 12m"
          [delta]="-18"
          sub="P50 · email‑to‑first‑touch"
          icon="timer"
          [sparkline]="sparkResponse()"
        />
        <vq-kpi
          label="SLA breaches"
          [value]="breachedCount()"
          [delta]="-22"
          sub="last 30d · 70/85/95 thresholds"
          icon="alert-triangle"
          [sparkline]="sparkBreaches()"
          sparkColor="var(--bad)"
        />
      </div>

      <!-- Volume + path distribution -->
      <div class="grid grid-cols-12 gap-3 mb-3">
        <div class="panel p-4 col-span-8" style="border-radius:4px;">
          <vq-section-head
            title="Query volume by routing path"
            desc="Stacked daily counts · Path A (AI‑resolved) · Path B (human team) · Path C (low‑confidence triage)"
          >
            <div class="flex items-center gap-3 text-[11.5px] mono">
              <span class="flex items-center gap-1.5">
                <span style="width:8px; height:8px; background: var(--path-a); border-radius:2px;"></span>
                A · {{ totalA() }}
              </span>
              <span class="flex items-center gap-1.5">
                <span style="width:8px; height:8px; background: var(--path-b); border-radius:2px;"></span>
                B · {{ totalB() }}
              </span>
              <span class="flex items-center gap-1.5">
                <span style="width:8px; height:8px; background: var(--path-c); border-radius:2px;"></span>
                C · {{ totalC() }}
              </span>
            </div>
          </vq-section-head>
          <vq-volume-chart [data]="trend" />
        </div>
        <div class="panel p-4 col-span-4" style="border-radius:4px;">
          <vq-section-head title="Path distribution" desc="Current 30d resolution mix" />
          <vq-path-pie [a]="totalA()" [b]="totalB()" [c]="totalC()" />
          <div class="mt-4 pt-4 border-t hairline" style="font-size:12px;">
            <div class="muted mb-2">Confidence threshold</div>
            <div class="flex items-center justify-between">
              <vq-mono>≥ 0.85 → A or B</vq-mono>
              <vq-mono [color]="'var(--ok)'">92.6%</vq-mono>
            </div>
            <div class="flex items-center justify-between mt-1">
              <vq-mono>&lt; 0.85 → triage (C)</vq-mono>
              <vq-mono [color]="'var(--warn)'">7.4%</vq-mono>
            </div>
          </div>
        </div>
      </div>

      <!-- Confidence + Hourly + SLA team -->
      <div class="grid grid-cols-12 gap-3 mb-3">
        <div class="panel p-4 col-span-4" style="border-radius:4px;">
          <vq-section-head title="Confidence histogram" desc="Last 30d · LLM Gateway scoring" />
          <vq-confidence-chart [data]="confidenceHist" />
          <div class="mt-2 muted" style="font-size:11px;">
            <span class="inline-flex items-center gap-1">
              <span style="width:6px; height:6px; background: var(--accent); border-radius:1px;"></span>
              0.85 cutoff
            </span>
          </div>
        </div>
        <div class="panel p-4 col-span-4" style="border-radius:4px;">
          <vq-section-head title="Hourly throughput" desc="Last 24h · ingested vs. resolved" />
          <vq-hourly-chart [data]="hourly" />
          <div class="mt-2 flex items-center gap-3 text-[11px] mono">
            <span class="flex items-center gap-1.5">
              <span style="width:8px; height:8px; background: var(--ink-2); border-radius:2px;"></span>
              Ingested
            </span>
            <span class="flex items-center gap-1.5">
              <span style="width:8px; height:8px; background: var(--accent); border-radius:2px;"></span>
              Resolved
            </span>
          </div>
        </div>
        <div class="panel p-4 col-span-4" style="border-radius:4px;">
          <vq-section-head title="SLA performance by team" desc="On‑time vs. breached · 30d" />
          <vq-sla-team-chart [data]="slaByTeam" />
        </div>
      </div>

      <!-- Recent queries + side widgets -->
      <div class="grid grid-cols-12 gap-3">
        <div class="panel col-span-8" style="border-radius:4px;">
          <div class="flex items-center justify-between p-4 border-b hairline">
            <div>
              <div class="ink" style="font-size:14px; font-weight:600;">Recent queries</div>
              <div class="muted mt-0.5" style="font-size:12px;">Newest 8 across all paths</div>
            </div>
            <button class="btn btn-ghost" (click)="goInbox()">
              <vq-icon name="arrow-right" [size]="13" /> Open inbox
            </button>
          </div>
          <table class="vqms-table">
            <thead>
              <tr>
                <th>Query</th><th>Vendor</th><th>Path</th><th>Status</th>
                <th>Conf.</th><th>SLA</th><th style="text-align:right">Received</th>
              </tr>
            </thead>
            <tbody>
              @for (q of recent(); track q.query_id) {
                <tr (click)="open(q)">
                  <td>
                    <div class="flex items-center gap-2">
                      <vq-priority [p]="q.priority" />
                      <vq-mono [color]="'var(--ink)'" [weight]="500">{{ q.query_id }}</vq-mono>
                    </div>
                    <div class="muted truncate mt-0.5" style="font-size:11.5px; max-width:380px;">
                      {{ q.subject }}
                    </div>
                  </td>
                  <td>
                    <div class="flex items-center gap-2">
                      <span class="ink-2" style="font-size:12.5px;">{{ q.vendor_name }}</span>
                      <vq-tier [tier]="q.vendor_tier" />
                    </div>
                    <vq-mono cssClass="muted" [size]="11">{{ q.vendor_id }}</vq-mono>
                  </td>
                  <td><vq-path-badge [letter]="q.processing_path" /></td>
                  <td><vq-status [value]="q.status" /></td>
                  <td><vq-confidence-bar [value]="q.confidence" /></td>
                  <td><vq-sla-bar [pct]="q.sla_pct" /></td>
                  <td style="text-align:right;"><vq-mono cssClass="muted">{{ relative(q.received_at) }}</vq-mono></td>
                </tr>
              }
            </tbody>
          </table>
        </div>

        <div class="col-span-4 flex flex-col gap-3">
          <div class="panel p-4" style="border-radius:4px;">
            <vq-section-head title="Top intents" desc="Last 30d · top 6" />
            <div class="flex flex-col gap-2 mt-1">
              @for (it of topIntents; track it.intent) {
                <div>
                  <div class="flex items-center justify-between text-[12px]">
                    <span class="ink-2">{{ it.intent }}</span>
                    <vq-mono cssClass="muted">{{ it.n }}</vq-mono>
                  </div>
                  <div style="height:3px; background: var(--line); border-radius:2px; margin-top:3px; overflow:hidden;">
                    <div
                      [style.width.%]="(it.n / topMax) * 100"
                      style="height:100%; background: var(--accent);"
                    ></div>
                  </div>
                </div>
              }
            </div>
          </div>
          <div class="panel p-4" style="border-radius:4px;">
            <vq-section-head title="Vendor health" desc="Tier‑weighted score · open queries" />
            <div class="flex flex-col gap-2.5 mt-1">
              @for (v of vendorTop(); track v.vendor_id) {
                <div class="flex items-center gap-3">
                  <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2">
                      <vq-tier [tier]="v.tier" />
                      <span class="ink truncate" style="font-size:13px;">{{ v.name }}</span>
                    </div>
                    <div class="muted" style="font-size:11px;">{{ v.open_queries }} open · {{ v.p1_open }} P1</div>
                  </div>
                  <div [style.width.px]="70">
                    <div style="height:4px; background: var(--line); border-radius:2px; overflow:hidden;">
                      <div
                        [style.width.%]="v.health"
                        style="height:100%;"
                        [style.background]="
                          v.health > 85
                            ? 'var(--ok)'
                            : v.health > 70
                              ? 'var(--warn)'
                              : 'var(--bad)'
                        "
                      ></div>
                    </div>
                  </div>
                  <vq-mono [size]="12" style="width:28px; text-align:right;">{{ v.health }}</vq-mono>
                </div>
              }
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
})
export class OverviewPage {
  readonly #router = inject(Router);
  readonly #drawer = inject(DrawerService);
  readonly #vendors = inject(VendorsStore);
  readonly #queries = inject(QueriesStore);
  protected readonly role = inject(RoleService);

  protected readonly endpointsOpen = signal(false);
  protected readonly endpoints = ENDPOINTS_OVERVIEW;

  protected readonly trend = TREND_30D;
  protected readonly hourly = HOURLY_24H;
  protected readonly confidenceHist = CONFIDENCE_HIST;
  protected readonly slaByTeam = SLA_BY_TEAM;
  protected readonly topIntents = TOP_INTENTS;
  protected readonly topMax = Math.max(...TOP_INTENTS.map((i) => i.n));
  protected readonly vendorTop = computed(() => this.#vendors.vendors().slice(0, 6));

  protected readonly today = new Date().toLocaleString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  });

  protected readonly totalA = computed(
    () => this.#queries.list().filter((q) => q.processing_path === 'A').length,
  );
  protected readonly totalB = computed(
    () => this.#queries.list().filter((q) => q.processing_path === 'B').length,
  );
  protected readonly totalC = computed(
    () => this.#queries.list().filter((q) => q.processing_path === 'C').length,
  );

  protected readonly breachedCount = computed(
    () =>
      this.#queries.list().filter((q) => q.sla_pct !== null && q.sla_pct >= 95).length,
  );

  protected readonly recent = computed(() =>
    [...this.#queries.list()]
      .sort((a, b) => b.received_at.localeCompare(a.received_at))
      .slice(0, 8),
  );

  protected readonly sparkReceived = computed<readonly number[]>(() =>
    TREND_30D.map((d) => d.received),
  );
  protected readonly sparkSla = computed<readonly number[]>(() =>
    TREND_30D.map((d) => 92 + Math.sin(d.A) * 3),
  );
  protected readonly sparkResponse = computed<readonly number[]>(() =>
    TREND_30D.map((d) => 250 - d.A),
  );
  protected readonly sparkBreaches = computed<readonly number[]>(() =>
    TREND_30D.map((_, i) => 14 - (i % 6)),
  );

  protected open(q: import('../data/models').Query): void {
    this.#drawer.showQuery(q);
  }

  protected goInbox(): void {
    this.#router.navigate(['/app/inbox']);
  }

  protected relative(iso: string): string {
    return relativeTime(iso);
  }
}
