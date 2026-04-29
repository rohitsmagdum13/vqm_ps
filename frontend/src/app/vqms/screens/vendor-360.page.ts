import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';
import { Location } from '@angular/common';
import { Icon } from '../ui/icon';
import { Mono } from '../ui/mono';
import { Avatar } from '../ui/avatar';
import { Tier } from '../ui/tier';
import { Donut } from '../ui/donut';
import { Status } from '../ui/status';
import { PathBadge } from '../ui/path-badge';
import { ConfidenceBar } from '../ui/confidence-bar';
import { SlaBar } from '../ui/sla-bar';
import { Empty } from '../ui/empty';
import { SectionHead } from '../ui/section-head';
import { EndpointsButton } from '../ui/endpoints-button';
import { EndpointsDrawer } from '../ui/endpoints-drawer';
import { VolumeChart } from '../charts/volume-chart';
import {
  CONTACTS,
  CONTRACTS,
  TREND_30D,
  relativeTime,
} from '../data/mock-data';
import { ENDPOINTS_VENDOR360 } from '../data/endpoints';
import { DrawerService } from '../services/drawer.service';
import { QueriesStore } from '../services/queries.store';
import { RoleService } from '../services/role.service';
import { VendorsStore } from '../services/vendors.store';
import type { Query, Vendor } from '../data/models';

type Tab = 'overview' | 'queries' | 'contacts' | 'contracts' | 'documents' | 'timeline';

interface TimelineItem {
  readonly ts: string;
  readonly who: string;
  readonly dir: 'in' | 'out';
  readonly text: string;
}

const TIMELINE: readonly TimelineItem[] = [
  {
    ts: 'Apr 28, 11:14',
    who: 'Marcus Holloway',
    dir: 'in',
    text: 'Inbound · Re: INV-88241 short paid by $1,847',
  },
  {
    ts: 'Apr 28, 11:15',
    who: 'VQMS',
    dir: 'out',
    text: 'Auto‑resolution drafted · Path A · sent',
  },
  {
    ts: 'Apr 27, 16:02',
    who: 'Priya Raman',
    dir: 'in',
    text: 'Inbound · banking detail change request',
  },
  {
    ts: 'Apr 27, 16:03',
    who: 'Niraj Shah',
    dir: 'out',
    text: 'Manual response sent · verification protocol enclosed',
  },
  {
    ts: 'Apr 26, 09:48',
    who: 'Marcus Holloway',
    dir: 'in',
    text: 'Inbound · Q1 statement reconciliation',
  },
  {
    ts: 'Apr 22, 14:30',
    who: 'VQMS',
    dir: 'out',
    text: 'Acknowledgment · ServiceNow INC-2139891 created',
  },
];

const DOCUMENTS: readonly { name: string; size: string; date: string }[] = [
  { name: 'MSA — executed.pdf', size: '1.2 MB', date: '2024-01-04' },
  { name: 'W-9 (2026).pdf', size: '186 KB', date: '2026-01-08' },
  { name: 'Insurance certificate.pdf', size: '412 KB', date: '2026-04-15' },
  { name: 'DPA.pdf', size: '640 KB', date: '2024-01-04' },
];

@Component({
  selector: 'vq-vendor-360',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    Icon,
    Mono,
    Avatar,
    Tier,
    Donut,
    Status,
    PathBadge,
    ConfidenceBar,
    SlaBar,
    Empty,
    SectionHead,
    VolumeChart,
    EndpointsButton,
    EndpointsDrawer,
  ],
  template: `
    <div class="p-6 max-w-[1600px] mx-auto fade-up">
      <button class="btn btn-ghost mb-3" (click)="back()">
        <vq-icon name="arrow-left" [size]="13" /> Back
      </button>

      <div class="panel p-5 mb-3" style="border-radius:4px;">
        <div class="flex items-start justify-between gap-4">
          <div class="flex items-start gap-4">
            <div
              [style.width.px]="56"
              [style.height.px]="56"
              [style.background]="'var(--bg)'"
              [style.border]="'1px solid var(--line-strong)'"
              [style.border-radius.px]="6"
              [style.font-family]="'JetBrains Mono'"
              style="display:flex; align-items:center; justify-content:center; font-size:22px; font-weight:600;"
            >
              {{ initials() }}
            </div>
            <div>
              <div class="flex items-center gap-2 mb-1">
                <span class="ink" style="font-size:22px; font-weight:600; letter-spacing:-.02em;">{{
                  vendor().name
                }}</span>
                <vq-tier [tier]="vendor().tier" />
                <vq-mono cssClass="muted">{{ vendor().vendor_id }}</vq-mono>
              </div>
              <div class="muted" style="font-size:13px;">
                {{ vendor().category }} · {{ vendor().city
                }}{{ vendor().state !== '—' ? ', ' + vendor().state : '' }}, {{ vendor().country }}
                · <span class="mono">{{ vendor().website }}</span>
              </div>
              <div class="flex items-center gap-3 mt-3" style="font-size:12px;">
                <div class="flex flex-col">
                  <span class="muted uppercase" style="font-size:10px; letter-spacing:.04em;">Annual revenue</span>
                  <span class="ink mono" style="font-size:13px; font-weight:600;">
                    \${{ revenue(vendor().annual_revenue) }}
                  </span>
                </div>
                <div class="flex flex-col">
                  <span class="muted uppercase" style="font-size:10px; letter-spacing:.04em;">Payment terms</span>
                  <span class="ink mono" style="font-size:13px; font-weight:600;">{{ vendor().payment_terms }}</span>
                </div>
                <div class="flex flex-col">
                  <span class="muted uppercase" style="font-size:10px; letter-spacing:.04em;">SLA</span>
                  <span class="ink mono" style="font-size:13px; font-weight:600;">
                    {{ vendor().sla_response_hours }}h / {{ vendor().sla_resolution_days }}d
                  </span>
                </div>
                <div class="flex flex-col">
                  <span class="muted uppercase" style="font-size:10px; letter-spacing:.04em;">Onboarded</span>
                  <span class="ink mono" style="font-size:13px; font-weight:600;">{{ vendor().onboarded_date }}</span>
                </div>
              </div>
            </div>
          </div>
          <div class="flex flex-col items-end gap-2">
            <div class="flex items-center gap-2">
              <button class="btn"><vq-icon name="mail" [size]="13" /> Compose email</button>
              <button class="btn"><vq-icon name="external-link" [size]="13" /> Salesforce</button>
              <button class="btn btn-primary"><vq-icon name="pencil" [size]="13" /> Edit</button>
              <vq-endpoints-button (clicked)="endpointsOpen.set(true)" />
            </div>

            <vq-endpoints-drawer
              [open]="endpointsOpen()"
              title="Vendor 360 · backend contract"
              subtitle="vendors.py + queries.py + memory.py"
              [endpoints]="endpoints"
              [role]="role.role()"
              (closed)="endpointsOpen.set(false)"
            />
            <div class="flex items-center gap-3 mt-1">
              <vq-donut [pct]="vendor().health" />
              <div>
                <div class="muted uppercase" style="font-size:10px; letter-spacing:.04em;">Health</div>
                <vq-mono
                  [size]="18"
                  [weight]="600"
                  [color]="
                    vendor().health > 85
                      ? 'var(--ok)'
                      : vendor().health > 70
                        ? 'var(--warn)'
                        : 'var(--bad)'
                  "
                  >{{ vendor().health }}</vq-mono
                >
                <span class="muted" style="font-size:11px;">/100</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="border-b hairline flex items-center mb-4">
        @for (t of tabs; track t) {
          <span class="tab" [class.active]="tab() === t" (click)="tab.set(t)">
            {{ titleCase(t) }}
            @if (t === 'queries') {
              <vq-mono cssClass="ml-1.5 muted">{{ vendorQueries().length }}</vq-mono>
            }
            @if (t === 'contacts') {
              <vq-mono cssClass="ml-1.5 muted">{{ contacts().length }}</vq-mono>
            }
            @if (t === 'contracts') {
              <vq-mono cssClass="ml-1.5 muted">{{ contracts().length }}</vq-mono>
            }
          </span>
        }
      </div>

      @if (tab() === 'overview') {
        <div class="grid grid-cols-12 gap-3">
          <div class="panel p-4 col-span-8" style="border-radius:4px;">
            <vq-section-head title="Query history" desc="Last 30 days · all paths" />
            <vq-volume-chart [data]="trend()" />
          </div>
          <div class="panel p-4 col-span-4" style="border-radius:4px;">
            <vq-section-head title="At a glance" />
            <div class="flex flex-col gap-3">
              <div class="flex items-center justify-between">
                <span class="muted uppercase" style="font-size:10px; letter-spacing:.04em;">Open queries</span>
                <span class="ink mono" style="font-size:14px; font-weight:600;">{{ openCount() }}</span>
              </div>
              <div class="flex items-center justify-between">
                <span class="muted uppercase" style="font-size:10px; letter-spacing:.04em;">P1 open</span>
                <span
                  class="mono"
                  style="font-size:14px; font-weight:600;"
                  [style.color]="vendor().p1_open > 0 ? 'var(--bad)' : 'var(--ink)'"
                  >{{ vendor().p1_open }}</span
                >
              </div>
              <div class="flex items-center justify-between">
                <span class="muted uppercase" style="font-size:10px; letter-spacing:.04em;">Avg resolution (last 30d)</span>
                <span class="ink mono" style="font-size:14px; font-weight:600;">2h 18m</span>
              </div>
              <div class="flex items-center justify-between">
                <span class="muted uppercase" style="font-size:10px; letter-spacing:.04em;">Resolution rate</span>
                <span class="ink mono" style="font-size:14px; font-weight:600;">93.1%</span>
              </div>
              <div class="flex items-center justify-between">
                <span class="muted uppercase" style="font-size:10px; letter-spacing:.04em;">SLA on‑time</span>
                <span class="ink mono" style="font-size:14px; font-weight:600;">96.4%</span>
              </div>
            </div>
          </div>
          <div class="panel p-4 col-span-12" style="border-radius:4px;">
            <vq-section-head
              title="Communication timeline"
              desc="Inbound + outbound · last 14 days"
            />
            <div class="flex flex-col">
              @for (it of timeline; track it.ts + it.who) {
                <div class="flex items-start gap-3 py-2.5 border-b hairline last:border-0">
                  <vq-mono cssClass="muted" [size]="11" style="min-width:100px;">{{ it.ts }}</vq-mono>
                  <span
                    [style.background]="
                      it.dir === 'in'
                        ? 'color-mix(in oklch, var(--info) 14%, var(--panel))'
                        : 'color-mix(in oklch, var(--accent) 14%, var(--panel))'
                    "
                    [style.color]="it.dir === 'in' ? 'var(--info)' : 'var(--accent)'"
                    style="display:inline-flex; align-items:center; justify-content:center; width:22px; height:22px; border-radius:999px;"
                  >
                    <vq-icon [name]="it.dir === 'in' ? 'arrow-down-left' : 'arrow-up-right'" [size]="12" />
                  </span>
                  <div class="flex-1">
                    <div class="ink-2" style="font-size:12.5px;">{{ it.text }}</div>
                    <vq-mono cssClass="muted" [size]="11">{{ it.who }}</vq-mono>
                  </div>
                </div>
              }
            </div>
          </div>
        </div>
      }

      @if (tab() === 'queries') {
        <div class="panel" style="border-radius:4px; overflow:hidden;">
          <table class="vqms-table">
            <thead>
              <tr>
                <th>Query</th><th>Subject</th><th>Path</th><th>Status</th><th>Conf.</th>
                <th>SLA</th><th style="text-align:right">Received</th>
              </tr>
            </thead>
            <tbody>
              @for (q of vendorQueries(); track q.query_id) {
                <tr (click)="openQuery(q)">
                  <td><vq-mono [color]="'var(--ink)'" [weight]="500">{{ q.query_id }}</vq-mono></td>
                  <td><div class="ink-2 truncate" style="max-width: 380px;">{{ q.subject }}</div></td>
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
      }

      @if (tab() === 'contacts') {
        <div class="grid grid-cols-3 gap-3">
          @for (c of contacts(); track c.email) {
            <div class="panel p-4" style="border-radius:4px;">
              <div class="flex items-start gap-3">
                <vq-avatar [name]="c.name" [size]="40" />
                <div class="flex-1 min-w-0">
                  <div class="ink truncate" style="font-size:13.5px; font-weight:500;">{{ c.name }}</div>
                  <div class="muted" style="font-size:11.5px;">{{ c.role }}</div>
                </div>
              </div>
              <div class="mt-3 flex flex-col gap-1.5" style="font-size:11.5px;">
                <div class="flex items-center gap-2">
                  <vq-icon name="mail" [size]="11" cssClass="muted" /> <vq-mono>{{ c.email }}</vq-mono>
                </div>
                <div class="flex items-center gap-2">
                  <vq-icon name="phone" [size]="11" cssClass="muted" /> <vq-mono>{{ c.phone }}</vq-mono>
                </div>
              </div>
            </div>
          }
        </div>
      }

      @if (tab() === 'contracts') {
        <div class="panel" style="border-radius:4px; overflow:hidden;">
          <table class="vqms-table">
            <thead>
              <tr><th>Contract</th><th>Title</th><th>Value</th><th>Term</th><th>Status</th></tr>
            </thead>
            <tbody>
              @for (c of contracts(); track c.id) {
                <tr>
                  <td><vq-mono [color]="'var(--ink)'" [weight]="500">{{ c.id }}</vq-mono></td>
                  <td class="ink-2">{{ c.title }}</td>
                  <td><vq-mono>\${{ c.value.toLocaleString() }}</vq-mono></td>
                  <td><vq-mono cssClass="muted">{{ c.start }} → {{ c.end }}</vq-mono></td>
                  <td><vq-status value="RESOLVED" /></td>
                </tr>
              }
              @if (contracts().length === 0) {
                <tr><td colspan="5"><vq-empty title="No contracts on file" desc="None retrieved from Salesforce." /></td></tr>
              }
            </tbody>
          </table>
        </div>
      }

      @if (tab() === 'documents') {
        <div class="grid grid-cols-4 gap-3">
          @for (d of docs; track d.name) {
            <div class="panel p-4" style="border-radius:4px;">
              <vq-icon name="file-text" [size]="20" cssClass="muted mb-3" />
              <div class="ink-2" style="font-size:12.5px; font-weight:500;">{{ d.name }}</div>
              <vq-mono cssClass="muted mt-1" [size]="11">{{ d.size }} · {{ d.date }}</vq-mono>
            </div>
          }
        </div>
      }

      @if (tab() === 'timeline') {
        <div class="panel p-5" style="border-radius:4px;">
          <div class="flex flex-col">
            @for (it of timeline; track it.ts + it.who) {
              <div class="flex items-start gap-3 py-2.5 border-b hairline last:border-0">
                <vq-mono cssClass="muted" [size]="11" style="min-width:100px;">{{ it.ts }}</vq-mono>
                <span
                  [style.background]="
                    it.dir === 'in'
                      ? 'color-mix(in oklch, var(--info) 14%, var(--panel))'
                      : 'color-mix(in oklch, var(--accent) 14%, var(--panel))'
                  "
                  [style.color]="it.dir === 'in' ? 'var(--info)' : 'var(--accent)'"
                  style="display:inline-flex; align-items:center; justify-content:center; width:22px; height:22px; border-radius:999px;"
                >
                  <vq-icon [name]="it.dir === 'in' ? 'arrow-down-left' : 'arrow-up-right'" [size]="12" />
                </span>
                <div class="flex-1">
                  <div class="ink-2" style="font-size:12.5px;">{{ it.text }}</div>
                  <vq-mono cssClass="muted" [size]="11">{{ it.who }}</vq-mono>
                </div>
              </div>
            }
          </div>
        </div>
      }
    </div>
  `,
})
export class Vendor360Page {
  readonly #drawer = inject(DrawerService);
  readonly #location = inject(Location);
  readonly #store = inject(VendorsStore);
  readonly #queries = inject(QueriesStore);
  protected readonly role = inject(RoleService);

  readonly vendorId = input.required<string>();

  protected readonly endpointsOpen = signal(false);
  protected readonly endpoints = ENDPOINTS_VENDOR360;

  protected readonly tab = signal<Tab>('overview');
  protected readonly tabs: readonly Tab[] = [
    'overview',
    'queries',
    'contacts',
    'contracts',
    'documents',
    'timeline',
  ];
  protected readonly timeline = TIMELINE;
  protected readonly docs = DOCUMENTS;

  protected readonly vendor = computed<Vendor>(() => {
    const id = this.vendorId();
    const list = this.#store.vendors();
    return list.find((v) => v.vendor_id === id) ?? list[0]!;
  });

  protected readonly initials = computed<string>(() => {
    const name = this.vendor().name;
    return name
      .split(' ')
      .map((s) => s[0])
      .slice(0, 2)
      .join('');
  });

  protected readonly contacts = computed(() => CONTACTS[this.vendor().vendor_id] ?? []);
  protected readonly contracts = computed(() => CONTRACTS[this.vendor().vendor_id] ?? []);

  protected readonly vendorQueries = computed(() =>
    this.#queries.list().filter((q) => q.vendor_id === this.vendor().vendor_id),
  );

  protected readonly openCount = computed(
    () =>
      this.vendorQueries().filter((q) => !['RESOLVED', 'CLOSED'].includes(q.status)).length,
  );

  protected readonly trend = computed(() =>
    TREND_30D.map((d) => ({
      ...d,
      A: Math.round(d.A * 0.18),
      B: Math.round(d.B * 0.18),
      C: Math.round(d.C * 0.18),
    })),
  );

  protected back(): void {
    this.#location.back();
  }

  protected openQuery(q: Query): void {
    this.#drawer.showQuery(q);
  }

  protected revenue(n: number): string {
    return (n / 1_000_000).toFixed(1) + 'M';
  }

  protected relative(iso: string): string {
    return relativeTime(iso);
  }

  protected titleCase(s: string): string {
    return s.charAt(0).toUpperCase() + s.slice(1);
  }
}
