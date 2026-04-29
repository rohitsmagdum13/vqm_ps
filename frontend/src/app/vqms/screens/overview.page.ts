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
import { OverviewStore } from '../services/overview.store';
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
          <div class="ink flex items-center gap-2" style="font-size:22px; font-weight:600; letter-spacing:-.02em;">
            Operations overview
            @if (overview.status() === 'live') {
              <span class="chip" style="color: var(--ok); border-color: var(--ok); font-size:10.5px;">
                <vq-icon name="check-circle" [size]="10" /> Live · /admin/overview
              </span>
            } @else if (overview.status() === 'loading') {
              <span class="chip" style="font-size:10.5px;">
                <vq-icon name="rotate-cw" [size]="10" /> Loading…
              </span>
            } @else if (overview.status() === 'error') {
              <span
                class="chip"
                style="color: var(--bad); border-color: var(--bad); font-size:10.5px;"
                [title]="overview.error() ?? ''"
              >
                <vq-icon name="alert-circle" [size]="10" /> {{ overview.error() }}
              </span>
            } @else {
              <span class="chip" style="color: var(--muted); font-size:10.5px;">
                <vq-icon name="info" [size]="10" /> Mock data
              </span>
            }
          </div>
          <div class="muted mt-1" style="font-size:13px;">
            <span class="mono">{{ today }}</span> · Last 30 days · All vendors
          </div>
        </div>
        <div class="flex items-center gap-2">
          <button class="btn"><vq-icon name="calendar" [size]="13" /> Last 30 days</button>
          <button
            class="btn"
            (click)="refresh()"
            [disabled]="overview.status() === 'loading'"
            title="Reload from /admin/overview"
          >
            <vq-icon name="rotate-cw" [size]="13" /> Refresh
          </button>
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
          [value]="kpiReceived()"
          [delta]="kpiReceivedDelta()"
          [sub]="kpiReceivedSub()"
          icon="inbox"
          [sparkline]="sparkReceived()"
          sparkColor="var(--ink-2)"
        />
        <vq-kpi
          label="Resolution rate"
          [value]="kpiResolutionRate()"
          [delta]="kpiResolutionDelta()"
          [sub]="kpiResolutionSub()"
          icon="check-circle"
          [sparkline]="sparkSla()"
          sparkColor="var(--ok)"
        />
        <vq-kpi
          label="Avg response time"
          [value]="kpiResponseTime()"
          [delta]="kpiResponseDelta()"
          sub="email‑to‑first‑touch · last 30d"
          icon="timer"
          [sparkline]="sparkResponse()"
        />
        <vq-kpi
          label="SLA breaches"
          [value]="kpiBreaches()"
          [delta]="kpiBreachesDelta()"
          sub="L2 fired (95%) · last 30d"
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
          <vq-volume-chart [data]="trend()" />
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
          <vq-confidence-chart [data]="confidenceHist()" />
          <div class="mt-2 muted" style="font-size:11px;">
            <span class="inline-flex items-center gap-1">
              <span style="width:6px; height:6px; background: var(--accent); border-radius:1px;"></span>
              0.85 cutoff
            </span>
          </div>
        </div>
        <div class="panel p-4 col-span-4" style="border-radius:4px;">
          <vq-section-head title="Hourly throughput" desc="Last 24h · ingested vs. resolved" />
          <vq-hourly-chart [data]="hourly()" />
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
          <vq-sla-team-chart [data]="slaByTeam()" />
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
              @for (it of topIntents(); track it.intent) {
                <div>
                  <div class="flex items-center justify-between text-[12px]">
                    <span class="ink-2">{{ it.intent }}</span>
                    <vq-mono cssClass="muted">{{ it.n }}</vq-mono>
                  </div>
                  <div style="height:3px; background: var(--line); border-radius:2px; margin-top:3px; overflow:hidden;">
                    <div
                      [style.width.%]="topMax() ? (it.n / topMax()) * 100 : 0"
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
  protected readonly overview = inject(OverviewStore);

  protected readonly endpointsOpen = signal(false);
  protected readonly endpoints = ENDPOINTS_OVERVIEW;

  // ---- Chart data: live from /admin/overview, fallback to mock when
  // the store hasn't loaded (signed-out, Reviewer role, or first paint).
  // Returning empty live arrays as mock keeps a never-blank page during
  // dev when the DB has zero rows.
  protected readonly trend = computed(() => {
    const live = this.overview.data()?.volume_by_path;
    return live && live.length > 0 ? live : TREND_30D;
  });
  protected readonly hourly = computed(() => {
    const live = this.overview.data()?.hourly_throughput;
    return live && live.length > 0 ? live : HOURLY_24H;
  });
  protected readonly confidenceHist = computed(() => {
    const live = this.overview.data()?.confidence_histogram;
    // The histogram always has 5 bands even when empty; only fall back
    // to mock when there's literally nothing (i.e. endpoint failed).
    return live && live.length > 0 ? live : CONFIDENCE_HIST;
  });
  protected readonly slaByTeam = computed(() => {
    const live = this.overview.data()?.sla_by_team;
    return live && live.length > 0 ? live : SLA_BY_TEAM;
  });
  protected readonly topIntents = computed(() => {
    const live = this.overview.data()?.top_intents;
    return live && live.length > 0 ? live : TOP_INTENTS;
  });
  protected readonly topMax = computed(() =>
    Math.max(...this.topIntents().map((i) => i.n), 1),
  );
  protected readonly vendorTop = computed(() => this.#vendors.vendors().slice(0, 6));

  protected readonly today = new Date().toLocaleString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  });

  // Path mix: prefer live totals over per-row aggregation since the
  // backend aggregates over the full 30-day window, not just the
  // QueriesStore page.
  protected readonly totalA = computed(() => {
    const live = this.overview.data()?.path_mix.A;
    if (live !== undefined && live > 0) return live;
    return this.#queries.list().filter((q) => q.processing_path === 'A').length;
  });
  protected readonly totalB = computed(() => {
    const live = this.overview.data()?.path_mix.B;
    if (live !== undefined && live > 0) return live;
    return this.#queries.list().filter((q) => q.processing_path === 'B').length;
  });
  protected readonly totalC = computed(() => {
    const live = this.overview.data()?.path_mix.C;
    if (live !== undefined && live > 0) return live;
    return this.#queries.list().filter((q) => q.processing_path === 'C').length;
  });

  protected readonly recent = computed(() =>
    [...this.#queries.list()]
      .sort((a, b) => b.received_at.localeCompare(a.received_at))
      .slice(0, 8),
  );

  // ---- KPI tiles ----
  // Each tile has three pieces: a display value (string), a delta
  // percent (number passed straight to <vq-kpi>), and an optional sub
  // line. Helpers below format the raw numbers into the strings the
  // mockup used (1,284 / 91.4% / 4h 12m / 87).
  protected readonly kpiReceived = computed<string | number>(() => {
    const v = this.overview.data()?.kpis.queries_received;
    return v !== undefined ? this.formatInt(v) : '1,284';
  });
  protected readonly kpiReceivedDelta = computed<number | null>(() => {
    const d = this.overview.data()?.kpis.queries_received_delta_pct;
    return d !== undefined ? Math.round(d) : 12;
  });
  protected readonly kpiReceivedSub = computed<string>(() => {
    const v = this.overview.data()?.kpis.queries_received;
    if (v === undefined) return 'vs. previous 30d · 42.8/day avg';
    return `vs. previous 30d · ${(v / 30).toFixed(1)}/day avg`;
  });

  protected readonly kpiResolutionRate = computed<string>(() => {
    const r = this.overview.data()?.kpis.resolution_rate_pct;
    return r !== undefined ? `${r.toFixed(1)}%` : '91.4%';
  });
  protected readonly kpiResolutionDelta = computed<number | null>(() => {
    const d = this.overview.data()?.kpis.resolution_rate_delta_pct;
    return d !== undefined ? Math.round(d) : 2;
  });
  protected readonly kpiResolutionSub = computed<string>(() => {
    const data = this.overview.data();
    if (!data) return '1,174 of 1,284 · auto‑close enabled';
    const r = data.kpis.resolution_rate_pct;
    const total = data.kpis.queries_received;
    const resolved = Math.round((r / 100) * total);
    return `${this.formatInt(resolved)} of ${this.formatInt(total)} · auto‑close enabled`;
  });

  protected readonly kpiResponseTime = computed<string>(() => {
    const m = this.overview.data()?.kpis.avg_response_minutes;
    return m !== undefined ? this.formatMinutes(m) : '4h 12m';
  });
  protected readonly kpiResponseDelta = computed<number | null>(() => {
    const d = this.overview.data()?.kpis.avg_response_delta_pct;
    // For response time, smaller is better — the KPI tile colors deltas
    // green-positive / red-negative, so flip the sign so a real
    // improvement (say -20%) renders as a green decrease arrow.
    return d !== undefined ? -Math.round(d) : 18;
  });

  protected readonly kpiBreaches = computed<string | number>(() => {
    const v = this.overview.data()?.kpis.sla_breaches;
    if (v !== undefined) return this.formatInt(v);
    return this.#queries
      .list()
      .filter((q) => q.sla_pct !== null && q.sla_pct >= 95).length;
  });
  protected readonly kpiBreachesDelta = computed<number | null>(() => {
    const d = this.overview.data()?.kpis.sla_breaches_delta_pct;
    // Same sign-flip logic — fewer breaches is good news.
    return d !== undefined ? -Math.round(d) : 22;
  });

  // ---- KPI sparklines: pull from live arrays when present ----
  protected readonly sparkReceived = computed<readonly number[]>(() => {
    const live = this.overview.data()?.kpi_sparklines.received_per_day;
    return live && live.length > 0 ? live : TREND_30D.map((d) => d.received);
  });
  protected readonly sparkSla = computed<readonly number[]>(() => {
    const live = this.overview.data()?.kpi_sparklines.resolution_rate_per_day;
    if (live && live.length > 0) return live.map((r) => r * 100);
    return TREND_30D.map((d) => 92 + Math.sin(d.A) * 3);
  });
  protected readonly sparkResponse = computed<readonly number[]>(() => {
    const live = this.overview.data()?.kpi_sparklines.response_minutes_per_day;
    return live && live.length > 0 ? live : TREND_30D.map((d) => 250 - d.A);
  });
  protected readonly sparkBreaches = computed<readonly number[]>(() => {
    const live = this.overview.data()?.kpi_sparklines.breaches_per_day;
    return live && live.length > 0 ? live : TREND_30D.map((_, i) => 14 - (i % 6));
  });

  refresh(): void {
    void this.overview.refresh();
  }

  protected open(q: import('../data/models').Query): void {
    this.#drawer.showQuery(q);
  }

  protected goInbox(): void {
    this.#router.navigate(['/app/inbox']);
  }

  protected relative(iso: string): string {
    return relativeTime(iso);
  }

  // 1234 → "1,234"
  private formatInt(n: number): string {
    return n.toLocaleString('en-US');
  }

  // 252 → "4h 12m". 45 → "45m". 0 → "0m".
  private formatMinutes(minutes: number): string {
    if (minutes < 60) return `${minutes}m`;
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    return m === 0 ? `${h}h` : `${h}h ${m}m`;
  }
}
