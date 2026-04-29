import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { Icon } from '../ui/icon';
import { Mono } from '../ui/mono';
import { HealthDot } from '../ui/health-dot';
import { SectionHead } from '../ui/section-head';
import { Sparkline } from '../ui/sparkline';
import { EndpointsButton } from '../ui/endpoints-button';
import { EndpointsDrawer } from '../ui/endpoints-drawer';
import { EMAIL_PIPELINE, QUEUES, RECENT_INGEST } from '../data/mock-data';
import { ENDPOINTS_EMAIL_MONITOR } from '../data/endpoints';
import type { PriorityKey } from '../services/mail.api';
import { MailStore } from '../services/mail.store';
import { RoleService } from '../services/role.service';

interface ErrorGroup {
  readonly stage: string;
  readonly n: number;
  readonly latest: string;
  readonly note: string;
}

const ERROR_GROUPS: readonly ErrorGroup[] = [
  {
    stage: 'Attachment processor',
    n: 3,
    latest: '12m ago',
    note: 'Textract async timeout > 5min',
  },
  { stage: 'Vendor identifier', n: 0, latest: '—', note: 'no errors' },
  { stage: 'Thread correlator', n: 0, latest: '—', note: 'no errors' },
  { stage: 'S3 put', n: 1, latest: '4h ago', note: 'AccessDenied (transient)' },
];

interface PriorityTile {
  readonly key: PriorityKey;
  readonly value: number;
  readonly labelColor: string;
  readonly borderColor: string;
  readonly valueColor: string;
}

const PRIORITY_ORDER: readonly PriorityKey[] = ['Critical', 'High', 'Medium', 'Low'];

// Per-priority colour palette. Critical gets the strongest accent so the
// tile reads as "this needs attention" at a glance. Medium and Low stay
// neutral so they fade into the page when zero.
const PRIORITY_COLORS: Readonly<
  Record<PriorityKey, { label: string; border: string; value: string }>
> = {
  Critical: { label: 'var(--bad)', border: 'var(--bad)', value: 'var(--bad)' },
  High: { label: 'var(--warn)', border: 'var(--line-strong)', value: 'var(--ink)' },
  Medium: { label: 'var(--muted)', border: 'var(--line)', value: 'var(--ink)' },
  Low: { label: 'var(--muted)', border: 'var(--line)', value: 'var(--ink-2)' },
};

@Component({
  selector: 'vq-email-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Icon, Mono, HealthDot, SectionHead, Sparkline, EndpointsButton, EndpointsDrawer],
  template: `
    <div class="p-6 max-w-[1600px] mx-auto fade-up">
      <div class="flex items-center justify-between mb-5">
        <div>
          <div class="ink" style="font-size:20px; font-weight:600; letter-spacing:-.02em;">
            Email ingestion monitor
          </div>
          <div class="muted mt-1" style="font-size:12.5px;">
            Live pipeline · Microsoft Graph API → Amazon S3 → Amazon SQS → LangGraph
          </div>
        </div>
        <div class="flex items-center gap-2">
          <span class="chip">
            <span
              class="pulse-dot"
              style="display:inline-block; width:6px; height:6px; background: var(--ok); border-radius:999px; margin-right:6px;"
            ></span>
            Live · 5s polling
          </span>
          <button class="btn"><vq-icon name="rotate-cw" [size]="13" /> Refresh</button>
          <button class="btn"><vq-icon name="play" [size]="13" /> Reconcile poller</button>
          <vq-endpoints-button (clicked)="endpointsOpen.set(true)" />
        </div>
      </div>

      <vq-endpoints-drawer
        [open]="endpointsOpen()"
        title="Email pipeline · backend contract"
        subtitle="health.py · dashboard.py · admin.py"
        [endpoints]="endpoints"
        [role]="role.role()"
        (closed)="endpointsOpen.set(false)"
      />

      <!-- Stats strip: priority breakdown + 10-day sparklines.
           Backed by GET /emails/stats → MailStore. Renders even before
           stats arrive (zero-filled), and shows a small "stale" hint when
           the store isn't live so the operator knows to sign in / refresh. -->
      <div class="grid grid-cols-12 gap-3 mb-3">
        <div class="panel col-span-5 p-4" style="border-radius:4px;">
          <div class="flex items-center justify-between">
            <vq-section-head
              title="Priority breakdown"
              desc="Email-sourced queries · routing_decision.priority"
            />
            @if (statsStatus() !== 'live') {
              <span class="chip muted" style="font-size:10px;">{{ statsHint() }}</span>
            }
          </div>
          <div class="grid grid-cols-4 gap-2 mt-2">
            @for (p of priorityTiles(); track p.key) {
              <div
                class="panel p-3"
                style="border-radius:4px; background: var(--bg);"
                [style.border-color]="p.borderColor"
              >
                <div
                  class="muted uppercase"
                  style="font-size:9.5px; letter-spacing:.04em;"
                  [style.color]="p.labelColor"
                >
                  {{ p.key }}
                </div>
                <vq-mono [size]="22" [weight]="600" [color]="p.valueColor">{{ p.value }}</vq-mono>
              </div>
            }
          </div>
        </div>

        <div class="panel col-span-7 p-4" style="border-radius:4px;">
          <vq-section-head
            title="Past 10 days · ingestion vs resolution"
            desc="New emails created vs resolved per day · oldest → newest"
          />
          <div class="grid grid-cols-2 gap-3 mt-2">
            <div class="panel p-3" style="border-radius:4px; background: var(--bg);">
              <div class="flex items-center justify-between">
                <span
                  class="muted uppercase"
                  style="font-size:10px; letter-spacing:.04em;"
                >
                  New (10d)
                </span>
                <vq-mono [size]="14" [weight]="600">{{ newTotal() }}</vq-mono>
              </div>
              <div class="mt-2">
                <vq-sparkline
                  [data]="newSeries()"
                  [height]="36"
                  [color]="'var(--accent)'"
                />
              </div>
              <div class="muted mt-1 flex justify-between" style="font-size:10px;">
                <span>{{ daysAgoLabel() }}</span>
                <span>today · <vq-mono [size]="10">{{ newToday() }}</vq-mono></span>
              </div>
            </div>

            <div class="panel p-3" style="border-radius:4px; background: var(--bg);">
              <div class="flex items-center justify-between">
                <span
                  class="muted uppercase"
                  style="font-size:10px; letter-spacing:.04em;"
                >
                  Resolved (10d)
                </span>
                <vq-mono [size]="14" [weight]="600">{{ resolvedTotal() }}</vq-mono>
              </div>
              <div class="mt-2">
                <vq-sparkline
                  [data]="resolvedSeries()"
                  [height]="36"
                  [color]="'var(--ok)'"
                />
              </div>
              <div class="muted mt-1 flex justify-between" style="font-size:10px;">
                <span>{{ daysAgoLabel() }}</span>
                <span>today · <vq-mono [size]="10">{{ resolvedToday() }}</vq-mono></span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Pipeline visual -->
      <div class="panel p-5 mb-3" style="border-radius:4px;">
        <vq-section-head
          title="Ingestion pipeline"
          desc="Per-stage in / out / errors / median latency · last 60 minutes"
        />
        <div class="flex items-stretch gap-2 overflow-x-auto py-2">
          @for (s of pipeline; track s.stage; let last = $last) {
            <div
              class="panel p-3 flex-1"
              style="border-radius:4px; background: var(--bg); min-width: 180px;"
            >
              <div class="flex items-start justify-between">
                <div class="ink-2" style="font-size:12.5px; font-weight:500;">{{ s.stage }}</div>
                <vq-health-dot [status]="s.errors > 0 ? 'degraded' : 'healthy'" />
              </div>
              <div class="grid grid-cols-3 gap-2 mt-3">
                <div>
                  <div class="muted uppercase" style="font-size:9.5px; letter-spacing:.04em;">In</div>
                  <vq-mono [size]="14" [weight]="600">{{ s.in }}</vq-mono>
                </div>
                <div>
                  <div class="muted uppercase" style="font-size:9.5px; letter-spacing:.04em;">Out</div>
                  <vq-mono [size]="14" [weight]="600">{{ s.out }}</vq-mono>
                </div>
                <div>
                  <div class="muted uppercase" style="font-size:9.5px; letter-spacing:.04em;">Err</div>
                  <vq-mono
                    [size]="14"
                    [weight]="600"
                    [color]="s.errors > 0 ? 'var(--bad)' : 'var(--ink)'"
                    >{{ s.errors }}</vq-mono
                  >
                </div>
              </div>
              <vq-mono cssClass="muted mt-2 block" [size]="10.5">p50 {{ s.median_ms }}ms</vq-mono>
            </div>
            @if (!last) {
              <div class="flex items-center"><vq-icon name="chevron-right" [size]="14" cssClass="subtle" /></div>
            }
          }
        </div>
      </div>

      <div class="grid grid-cols-12 gap-3 mb-3">
        <div class="panel col-span-7" style="border-radius:4px; overflow:hidden;">
          <div class="p-4 border-b hairline">
            <vq-section-head
              title="Amazon SQS queue depth"
              desc="Visible · in‑flight · DLQ · oldest message age"
            />
          </div>
          <table class="vqms-table">
            <thead>
              <tr>
                <th>Queue</th><th>Visible</th><th>In‑flight</th><th>DLQ</th>
                <th>Oldest age</th><th>Throughput / min</th>
              </tr>
            </thead>
            <tbody>
              @for (q of queues; track q.name) {
                <tr>
                  <td><vq-mono [color]="'var(--ink)'" [weight]="500">{{ q.name }}</vq-mono></td>
                  <td><vq-mono>{{ q.visible }}</vq-mono></td>
                  <td><vq-mono>{{ q.in_flight }}</vq-mono></td>
                  <td>
                    <vq-mono [color]="q.dlq > 0 ? 'var(--bad)' : 'var(--ink)'">{{ q.dlq }}</vq-mono>
                  </td>
                  <td>
                    <vq-mono cssClass="muted">{{
                      q.oldest_age_s > 0 ? formatAge(q.oldest_age_s) : '—'
                    }}</vq-mono>
                  </td>
                  <td><vq-mono>{{ q.throughput_1m }}</vq-mono></td>
                </tr>
              }
            </tbody>
          </table>
        </div>

        <div class="panel col-span-5 p-4" style="border-radius:4px;">
          <vq-section-head title="Microsoft Graph subscription" desc="Webhook health · last 24h" />
          <div class="grid grid-cols-2 gap-3 mt-2">
            <div class="flex items-center justify-between">
              <span class="muted uppercase" style="font-size:10px; letter-spacing:.04em;">Active subscription</span>
              <vq-mono [size]="14" [weight]="600">✓ live</vq-mono>
            </div>
            <div class="flex items-center justify-between">
              <span class="muted uppercase" style="font-size:10px; letter-spacing:.04em;">Expires in</span>
              <vq-mono [size]="14" [weight]="600">3d 14h</vq-mono>
            </div>
            <div class="flex items-center justify-between">
              <span class="muted uppercase" style="font-size:10px; letter-spacing:.04em;">Notifications (24h)</span>
              <vq-mono [size]="14" [weight]="600">218</vq-mono>
            </div>
            <div class="flex items-center justify-between">
              <span class="muted uppercase" style="font-size:10px; letter-spacing:.04em;">429s (last hour)</span>
              <vq-mono [size]="14" [weight]="600" [color]="'var(--warn)'">14</vq-mono>
            </div>
            <div class="flex items-center justify-between">
              <span class="muted uppercase" style="font-size:10px; letter-spacing:.04em;">Avg fetch latency</span>
              <vq-mono [size]="14" [weight]="600">2.24s</vq-mono>
            </div>
            <div class="flex items-center justify-between">
              <span class="muted uppercase" style="font-size:10px; letter-spacing:.04em;">Reconcile lag</span>
              <vq-mono [size]="14" [weight]="600">4m 12s</vq-mono>
            </div>
          </div>
          <div class="mt-4 pt-4 border-t hairline">
            <div class="muted uppercase mb-2" style="font-size:10px; letter-spacing:.04em;">Subscription URL</div>
            <vq-mono [size]="11" cssClass="break-all">
              https://api.vqms.hexaware.com/webhooks/ms-graph
            </vq-mono>
          </div>
        </div>
      </div>

      <div class="grid grid-cols-12 gap-3">
        <div class="panel col-span-8" style="border-radius:4px; overflow:hidden;">
          <div class="p-4 border-b hairline">
            <vq-section-head
              title="Recent ingestion"
              desc="Webhook → vendor identification → SQS"
            />
          </div>
          <table class="vqms-table">
            <thead>
              <tr><th>Time</th><th>From</th><th>Subject</th><th>Vendor match</th><th>Outcome</th><th style="text-align:right">Lat.</th></tr>
            </thead>
            <tbody>
              @for (r of recent; track r.ts + r.from) {
                <tr>
                  <td><vq-mono cssClass="muted" [size]="11">{{ r.ts }}</vq-mono></td>
                  <td><vq-mono cssClass="ink-2" [size]="11.5">{{ r.from }}</vq-mono></td>
                  <td><span class="ink-2" style="font-size:12.5px;">{{ r.subject }}</span></td>
                  <td>
                    @if (r.vendor === '—') {
                      <span class="subtle">— no match</span>
                    } @else {
                      <vq-mono>{{ r.vendor }}</vq-mono>
                    }
                  </td>
                  <td>
                    @if (r.outcome === 'enqueued') {
                      <span class="chip" style="color: var(--ok); border-color: var(--ok);">Enqueued</span>
                    }
                    @if (r.outcome === 'filtered') {
                      <span class="chip">Filtered (noise)</span>
                    }
                    @if (r.outcome === 'ocr') {
                      <span class="chip" style="color: var(--info); border-color: var(--info);">OCR running</span>
                    }
                    @if (r.outcome === 'error') {
                      <span class="chip" style="color: var(--bad); border-color: var(--bad);">Error</span>
                    }
                  </td>
                  <td style="text-align:right;"><vq-mono cssClass="muted">{{ r.lat }}ms</vq-mono></td>
                </tr>
              }
            </tbody>
          </table>
        </div>

        <div class="panel col-span-4 p-4" style="border-radius:4px;">
          <vq-section-head title="Processing errors" desc="Last 24h · grouped by stage" />
          <div class="flex flex-col gap-2 mt-1">
            @for (e of errors; track e.stage) {
              <div
                class="flex items-start gap-3 p-3 rounded"
                [style.background]="e.n > 0 ? 'color-mix(in oklch, var(--bad) 6%, var(--panel))' : 'var(--bg)'"
              >
                <vq-icon
                  [name]="e.n > 0 ? 'alert-circle' : 'check-circle'"
                  [size]="14"
                  [cssClass]="''"
                />
                <div class="flex-1">
                  <div class="ink-2 flex items-center gap-2" style="font-size:12.5px;">
                    {{ e.stage }}
                    @if (e.n > 0) {
                      <vq-mono [color]="'var(--bad)'" [weight]="600">{{ e.n }}</vq-mono>
                    }
                  </div>
                  <div class="muted" style="font-size:11px;">{{ e.note }} · {{ e.latest }}</div>
                </div>
              </div>
            }
          </div>
        </div>
      </div>
    </div>
  `,
})
export class EmailPage {
  protected readonly role = inject(RoleService);
  protected readonly mail = inject(MailStore);
  protected readonly endpointsOpen = signal(false);
  protected readonly endpoints = ENDPOINTS_EMAIL_MONITOR;

  protected readonly pipeline = EMAIL_PIPELINE;
  protected readonly queues = QUEUES;
  protected readonly recent = RECENT_INGEST;
  protected readonly errors = ERROR_GROUPS;

  // ---- Stats strip (priority + 10-day sparklines) ----
  // All derived from MailStore.stats(); when the store hasn't loaded yet
  // we fall through to zero-filled defaults so the SVG never errors out
  // on an empty array.
  protected readonly statsStatus = this.mail.status;

  protected readonly priorityTiles = computed<readonly PriorityTile[]>(() => {
    const breakdown = this.mail.stats()?.priority_breakdown;
    return PRIORITY_ORDER.map((key) => {
      const palette = PRIORITY_COLORS[key];
      const value = breakdown?.[key] ?? 0;
      return {
        key,
        value,
        labelColor: palette.label,
        borderColor: palette.border,
        valueColor: palette.value,
      } satisfies PriorityTile;
    });
  });

  protected readonly newSeries = computed<readonly number[]>(
    () => this.mail.stats()?.past_10_days_new ?? new Array(10).fill(0),
  );
  protected readonly resolvedSeries = computed<readonly number[]>(
    () => this.mail.stats()?.past_10_days_resolved ?? new Array(10).fill(0),
  );

  protected readonly newToday = computed<number>(() => this.tail(this.newSeries()));
  protected readonly resolvedToday = computed<number>(() => this.tail(this.resolvedSeries()));
  protected readonly newTotal = computed<number>(
    () => this.newSeries().reduce((a, b) => a + b, 0),
  );
  protected readonly resolvedTotal = computed<number>(
    () => this.resolvedSeries().reduce((a, b) => a + b, 0),
  );

  protected readonly daysAgoLabel = (): string => '9d ago';

  protected readonly statsHint = computed<string>(() => {
    const s = this.statsStatus();
    if (s === 'loading') return 'loading…';
    if (s === 'error') return this.mail.error() ?? 'error';
    if (s === 'mock') return 'mock data';
    return 'stale';
  });

  private tail(arr: readonly number[]): number {
    return arr.length === 0 ? 0 : arr[arr.length - 1]!;
  }

  protected formatAge(s: number): string {
    if (s < 60) return `${s}s`;
    if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
    return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  }
}
