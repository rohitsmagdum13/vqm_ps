import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { Icon } from '../ui/icon';
import { Mono } from '../ui/mono';
import { Tier } from '../ui/tier';
import { Status } from '../ui/status';
import { Priority } from '../ui/priority';
import { PathBadge } from '../ui/path-badge';
import { ConfidenceBar } from '../ui/confidence-bar';
import { SlaBar } from '../ui/sla-bar';
import { Empty } from '../ui/empty';
import { EndpointsButton } from '../ui/endpoints-button';
import { EndpointsDrawer } from '../ui/endpoints-drawer';
import { relativeTime } from '../data/mock-data';
import { ENDPOINTS_INBOX } from '../data/endpoints';
import type { Query } from '../data/models';
import { DrawerService } from '../services/drawer.service';
import { QueriesStore } from '../services/queries.store';
import { RoleService } from '../services/role.service';
import { VendorsStore } from '../services/vendors.store';

interface Filters {
  status: string;
  path: string;
  vendor: string;
  priority: string;
  minConf: number;
  search: string;
}

interface SortBy {
  key: keyof Query;
  dir: 'asc' | 'desc';
}

interface SavedView {
  readonly id: string;
  readonly label: string;
  readonly icon: string;
  readonly desc: string;
  readonly filters: Filters;
}

const STATUS_OPTIONS: readonly string[] = [
  'ALL',
  'RESOLVED',
  'DELIVERING',
  'DRAFTING',
  'ROUTING',
  'ANALYZING',
  'AWAITING_RESOLUTION',
  'PAUSED',
  'REOPENED',
  'FAILED',
];

const DEFAULT_FILTERS: Filters = {
  status: 'ALL',
  path: 'ALL',
  vendor: 'ALL',
  priority: 'ALL',
  minConf: 0,
  search: '',
};

// Preset filter combinations. In production these would come from
// GET /queries/saved-views (per-user, persisted in workflow.saved_views).
const SAVED_VIEWS: readonly SavedView[] = [
  {
    id: 'my_path_c',
    label: 'Path C — needs review',
    icon: 'user-check',
    desc: 'Low-confidence cases waiting on a reviewer decision',
    filters: { ...DEFAULT_FILTERS, path: 'C', status: 'PAUSED' },
  },
  {
    id: 'p1_open',
    label: 'P1 — anything open',
    icon: 'alert-triangle',
    desc: 'Critical priority across every team',
    filters: { ...DEFAULT_FILTERS, priority: 'P1' },
  },
  {
    id: 'high_conf_drafts',
    label: 'High-confidence drafts',
    icon: 'sparkles',
    desc: 'Confidence ≥ 0.85 ready for one-click approval',
    filters: { ...DEFAULT_FILTERS, status: 'DRAFTING', minConf: 0.85 },
  },
  {
    id: 'awaiting_team',
    label: 'Awaiting team resolution',
    icon: 'clock',
    desc: 'Path B cases where a human team is investigating',
    filters: { ...DEFAULT_FILTERS, path: 'B', status: 'AWAITING_RESOLUTION' },
  },
  {
    id: 'routing_now',
    label: 'In routing',
    icon: 'route',
    desc: 'Just classified, picking team + SLA',
    filters: { ...DEFAULT_FILTERS, status: 'ROUTING' },
  },
  {
    id: 'low_conf_only',
    label: 'Low confidence (< 0.6)',
    icon: 'shield-alert',
    desc: 'Anything the model is unsure about — quality spot-check',
    filters: { ...DEFAULT_FILTERS, minConf: 0 },
  },
];

@Component({
  selector: 'vq-inbox-page',
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
    Empty,
    EndpointsButton,
    EndpointsDrawer,
  ],
  template: `
    <div class="p-6 max-w-[1600px] mx-auto fade-up">
      <div class="flex items-center justify-between mb-4">
        <div>
          <div class="ink" style="font-size:20px; font-weight:600; letter-spacing:-.02em;">Query inbox</div>
          <div class="muted mt-1" style="font-size:12.5px;">
            <vq-mono>{{ filtered().length }}</vq-mono> of <vq-mono>{{ total() }}</vq-mono> queries
            @if (selected().size > 0) {
              · <vq-mono [color]="'var(--accent)'">{{ selected().size }} selected</vq-mono>
            }
          </div>
        </div>
        <div class="flex items-center gap-2">
          @if (selected().size > 0) {
            @if (caps().approve) {
              <button class="btn"><vq-icon name="user-check" [size]="13" /> Approve drafts</button>
            }
            @if (caps().reroute) {
              <button class="btn"><vq-icon name="route" [size]="13" /> Reroute</button>
            }
            @if (caps().escalate) {
              <button class="btn"><vq-icon name="alert-triangle" [size]="13" /> Escalate</button>
            }
            <div style="width:1px; height:22px; background: var(--line);"></div>
          }
          <div style="position: relative;">
            <button class="btn" (click)="toggleSavedViews($event)">
              <vq-icon name="filter" [size]="13" />
              @if (activeView(); as v) {
                <span class="ink-2" style="font-size:12.5px;">{{ v.label }}</span>
              } @else {
                Saved views
              }
              <vq-icon name="chevron-down" [size]="11" cssClass="ml-1 muted" />
            </button>

            @if (savedViewsOpen()) {
              <div
                class="fixed inset-0 z-30"
                style="background: transparent;"
                (click)="savedViewsOpen.set(false)"
              ></div>
              <div
                class="panel fade-up"
                style="position: absolute; top: calc(100% + 4px); right: 0; width: 320px; z-index: 40; border-radius: 4px; box-shadow: 0 8px 24px rgba(0,0,0,.10);"
                (click)="$event.stopPropagation()"
              >
                <div
                  class="px-3 py-2 border-b hairline muted uppercase tracking-wider flex items-center gap-2"
                  style="font-size:10px; font-weight:600;"
                >
                  Saved views
                  <vq-mono cssClass="ml-auto" [size]="10">{{ savedViews.length }}</vq-mono>
                </div>
                <div class="p-1 max-h-[420px] overflow-y-auto">
                  @for (v of savedViews; track v.id) {
                    <button
                      type="button"
                      class="nav-item w-full text-left"
                      [class.active]="activeView()?.id === v.id"
                      (click)="applyView(v)"
                    >
                      <vq-icon [name]="v.icon" [size]="13" />
                      <div class="flex-1 min-w-0">
                        <div class="ink-2" style="font-size:12.5px; font-weight:500;">{{ v.label }}</div>
                        <div class="muted truncate" style="font-size:11px;">{{ v.desc }}</div>
                      </div>
                    </button>
                  }
                </div>
                <div class="border-t hairline p-2 flex items-center gap-2">
                  @if (activeView()) {
                    <button class="btn btn-ghost flex-1 justify-center" (click)="clearView()">
                      <vq-icon name="x" [size]="12" /> Clear
                    </button>
                  }
                  <button class="btn flex-1 justify-center" title="POST /queries/saved-views — proposed">
                    <vq-icon name="plus" [size]="12" /> Save current
                  </button>
                </div>
              </div>
            }
          </div>
          <button class="btn"><vq-icon name="download" [size]="13" /> Export CSV</button>
          @if (caps().editVendor) {
            <button class="btn btn-primary"><vq-icon name="plus" [size]="13" /> New query</button>
          }
          <vq-endpoints-button (clicked)="endpointsOpen.set(true)" />
        </div>
      </div>

      <vq-endpoints-drawer
        [open]="endpointsOpen()"
        title="Query inbox · backend contract"
        subtitle="src/api/routes/queries.py"
        [endpoints]="endpoints"
        [role]="role.role()"
        (closed)="endpointsOpen.set(false)"
      />

      <!-- Filter bar -->
      <div class="panel p-3 flex items-center gap-2 flex-wrap mb-3" style="border-radius:4px;">
        <div class="relative flex-1" style="min-width:260px;">
          <span style="position:absolute; left:10px; top:50%; transform:translateY(-50%);">
            <vq-icon name="search" [size]="14" cssClass="muted" />
          </span>
          <input
            class="w-full"
            style="padding-left: 32px;"
            placeholder="Search VQ‑id, subject, vendor…"
            [value]="filters().search"
            (input)="setFilter('search', input($event))"
          />
        </div>
        <div class="inline-flex items-center">
          <span class="muted text-[10.5px] uppercase mr-2" style="letter-spacing:.04em;">Status</span>
          <select
            [value]="filters().status"
            (change)="setFilter('status', input($event))"
            style="min-width: 110px; font-size:12.5px;"
          >
            @for (o of statusOptions; track o) {
              <option>{{ o }}</option>
            }
          </select>
        </div>
        <div class="inline-flex items-center">
          <span class="muted text-[10.5px] uppercase mr-2" style="letter-spacing:.04em;">Path</span>
          <select
            [value]="filters().path"
            (change)="setFilter('path', input($event))"
            style="min-width: 110px; font-size:12.5px;"
          >
            <option value="ALL">All paths</option>
            <option value="A">Path A</option>
            <option value="B">Path B</option>
            <option value="C">Path C</option>
          </select>
        </div>
        <div class="inline-flex items-center">
          <span class="muted text-[10.5px] uppercase mr-2" style="letter-spacing:.04em;">Vendor</span>
          <select
            [value]="filters().vendor"
            (change)="setFilter('vendor', input($event))"
            style="min-width: 110px; font-size:12.5px;"
          >
            <option value="ALL">All vendors</option>
            @for (v of vendors(); track v.vendor_id) {
              <option [value]="v.vendor_id">{{ v.name }}</option>
            }
          </select>
        </div>
        <div class="inline-flex items-center">
          <span class="muted text-[10.5px] uppercase mr-2" style="letter-spacing:.04em;">Priority</span>
          <select
            [value]="filters().priority"
            (change)="setFilter('priority', input($event))"
            style="min-width: 90px; font-size:12.5px;"
          >
            <option>ALL</option><option>P1</option><option>P2</option><option>P3</option>
          </select>
        </div>
        <div class="flex items-center gap-2 px-2 py-1.5">
          <span class="muted text-[11px] uppercase" style="letter-spacing:.04em;">Min conf</span>
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            [value]="filters().minConf"
            (input)="setFilter('minConf', input($event))"
            style="width:90px; padding:0; accent-color: var(--accent);"
          />
          <vq-mono style="width:28px;">{{ filters().minConf.toFixed(2) }}</vq-mono>
        </div>
      </div>

      <!-- Table -->
      <div class="panel" style="border-radius:4px; overflow:hidden;">
        <table class="vqms-table">
          <thead>
            <tr>
              <th style="width:32px;">
                <input
                  type="checkbox"
                  [checked]="allSelected()"
                  (change)="toggleAll()"
                  style="accent-color: var(--accent);"
                />
              </th>
              <th><button class="inline-flex items-center gap-1" (click)="setSort('query_id')">Query @if (sortBy().key === 'query_id') { <vq-icon [name]="sortBy().dir === 'asc' ? 'chevron-up' : 'chevron-down'" [size]="11" /> }</button></th>
              <th><button class="inline-flex items-center gap-1" (click)="setSort('vendor_name')">Vendor @if (sortBy().key === 'vendor_name') { <vq-icon [name]="sortBy().dir === 'asc' ? 'chevron-up' : 'chevron-down'" [size]="11" /> }</button></th>
              <th>Subject / Intent</th>
              <th><button class="inline-flex items-center gap-1" (click)="setSort('processing_path')">Path @if (sortBy().key === 'processing_path') { <vq-icon [name]="sortBy().dir === 'asc' ? 'chevron-up' : 'chevron-down'" [size]="11" /> }</button></th>
              <th><button class="inline-flex items-center gap-1" (click)="setSort('status')">Status @if (sortBy().key === 'status') { <vq-icon [name]="sortBy().dir === 'asc' ? 'chevron-up' : 'chevron-down'" [size]="11" /> }</button></th>
              <th><button class="inline-flex items-center gap-1" (click)="setSort('confidence')">Conf. @if (sortBy().key === 'confidence') { <vq-icon [name]="sortBy().dir === 'asc' ? 'chevron-up' : 'chevron-down'" [size]="11" /> }</button></th>
              <th>SLA</th>
              <th>Team / Ticket</th>
              <th style="text-align:right">
                <button class="inline-flex items-center gap-1" (click)="setSort('received_at')">
                  Received
                  @if (sortBy().key === 'received_at') {
                    <vq-icon [name]="sortBy().dir === 'asc' ? 'chevron-up' : 'chevron-down'" [size]="11" />
                  }
                </button>
              </th>
            </tr>
          </thead>
          <tbody>
            @if (filtered().length === 0) {
              <tr>
                <td colspan="10">
                  <vq-empty title="No queries match" desc="Try clearing a filter or expanding the date window." />
                </td>
              </tr>
            }
            @for (q of filtered(); track q.query_id) {
              <tr [class.selected]="selected().has(q.query_id)" (click)="open(q)">
                <td (click)="$event.stopPropagation(); toggle(q.query_id)">
                  <input
                    type="checkbox"
                    [checked]="selected().has(q.query_id)"
                    (click)="$event.stopPropagation()"
                    style="accent-color: var(--accent);"
                  />
                </td>
                <td>
                  <div class="flex items-center gap-2">
                    <vq-priority [p]="q.priority" />
                    <vq-mono [color]="'var(--ink)'" [weight]="500">{{ q.query_id }}</vq-mono>
                    @if (q.reopened) {
                      <span class="chip" style="font-size:9.5px; padding:1px 5px;">REOPENED</span>
                    }
                  </div>
                  <vq-mono cssClass="muted" [size]="10.5">
                    {{ q.source }} · {{ q.attachments > 0 ? q.attachments + ' att.' : 'no att.' }}
                  </vq-mono>
                </td>
                <td>
                  <div class="ink-2" style="font-size:12.5px;">{{ q.vendor_name }}</div>
                  <div class="flex items-center gap-1.5 mt-0.5">
                    <vq-tier [tier]="q.vendor_tier" />
                    <vq-mono cssClass="muted" [size]="10.5">{{ q.vendor_id }}</vq-mono>
                  </div>
                </td>
                <td>
                  <div class="ink-2 truncate" style="font-size:12.5px; max-width: 320px;">{{ q.subject }}</div>
                  <div class="muted mt-0.5" style="font-size:11px;">{{ q.intent }}</div>
                </td>
                <td><vq-path-badge [letter]="q.processing_path" size="sm" /></td>
                <td><vq-status [value]="q.status" /></td>
                <td><vq-confidence-bar [value]="q.confidence" /></td>
                <td><vq-sla-bar [pct]="q.sla_pct" /></td>
                <td>
                  <div class="ink-2" style="font-size:12px;">{{ q.assigned_team }}</div>
                  @if (q.ticket_id) {
                    <vq-mono cssClass="muted" [size]="10.5">{{ q.ticket_id }}</vq-mono>
                  }
                </td>
                <td style="text-align:right;">
                  <vq-mono cssClass="muted">{{ relative(q.received_at) }}</vq-mono>
                </td>
              </tr>
            }
          </tbody>
        </table>

        <div class="flex items-center justify-between p-3 border-t hairline">
          <div class="muted" style="font-size:12px;">
            Showing 1–{{ filtered().length }} of {{ filtered().length }}
          </div>
          <div class="flex items-center gap-1">
            <button class="btn btn-ghost" disabled><vq-icon name="chevron-left" [size]="13" /></button>
            <vq-mono cssClass="px-2">1 / 1</vq-mono>
            <button class="btn btn-ghost" disabled><vq-icon name="chevron-right" [size]="13" /></button>
          </div>
        </div>
      </div>
    </div>
  `,
})
export class InboxPage {
  readonly #drawer = inject(DrawerService);
  readonly #role = inject(RoleService);
  readonly #vendorsStore = inject(VendorsStore);
  readonly #queriesStore = inject(QueriesStore);

  protected readonly statusOptions = STATUS_OPTIONS;
  protected readonly vendors = this.#vendorsStore.vendors;
  protected readonly all = this.#queriesStore.list;
  protected readonly total = computed<number>(() => this.all().length);
  protected readonly caps = this.#role.caps;
  protected readonly role = this.#role;
  protected readonly endpointsOpen = signal(false);
  protected readonly endpoints = ENDPOINTS_INBOX;

  protected readonly savedViews = SAVED_VIEWS;
  protected readonly savedViewsOpen = signal(false);

  protected readonly filters = signal<Filters>({ ...DEFAULT_FILTERS });

  protected readonly selected = signal<Set<string>>(new Set());
  protected readonly sortBy = signal<SortBy>({ key: 'received_at', dir: 'desc' });

  protected readonly filtered = computed<readonly Query[]>(() => {
    const f = this.filters();
    const { key, dir } = this.sortBy();
    const list = this.all().filter((q) => {
      if (f.status !== 'ALL' && q.status !== f.status) return false;
      if (f.path !== 'ALL' && q.processing_path !== f.path) return false;
      if (f.vendor !== 'ALL' && q.vendor_id !== f.vendor) return false;
      if (f.priority !== 'ALL' && q.priority !== f.priority) return false;
      if (q.confidence < f.minConf) return false;
      if (f.search) {
        const s = f.search.toLowerCase();
        if (
          !q.query_id.toLowerCase().includes(s) &&
          !q.subject.toLowerCase().includes(s) &&
          !q.vendor_name.toLowerCase().includes(s)
        ) {
          return false;
        }
      }
      return true;
    });
    list.sort((a, b) => {
      const av = a[key] as string | number | null | undefined;
      const bv = b[key] as string | number | null | undefined;
      let cmp = 0;
      if (av === null || av === undefined) cmp = -1;
      else if (bv === null || bv === undefined) cmp = 1;
      else cmp = av > bv ? 1 : av < bv ? -1 : 0;
      return dir === 'asc' ? cmp : -cmp;
    });
    return list;
  });

  protected readonly allSelected = computed(
    () => this.selected().size === this.filtered().length && this.filtered().length > 0,
  );

  // A view is "active" when every non-search filter equals one of the presets.
  // Search text is ignored so the user can keep refining inside an active view.
  protected readonly activeView = computed<SavedView | null>(() => {
    const f = this.filters();
    return (
      this.savedViews.find(
        (v) =>
          v.filters.status === f.status &&
          v.filters.path === f.path &&
          v.filters.vendor === f.vendor &&
          v.filters.priority === f.priority &&
          v.filters.minConf === f.minConf,
      ) ?? null
    );
  });

  protected setFilter<K extends keyof Filters>(key: K, value: string): void {
    const next: Filters = { ...this.filters() };
    if (key === 'minConf') next.minConf = Number(value);
    else (next as unknown as Record<string, string>)[key] = value;
    this.filters.set(next);
  }

  protected toggleSavedViews(e: MouseEvent): void {
    e.stopPropagation();
    this.savedViewsOpen.update((v) => !v);
  }

  protected applyView(v: SavedView): void {
    // Preserve the user's current search text; replace the rest.
    this.filters.set({ ...v.filters, search: this.filters().search });
    this.savedViewsOpen.set(false);
  }

  protected clearView(): void {
    this.filters.set({ ...DEFAULT_FILTERS, search: this.filters().search });
    this.savedViewsOpen.set(false);
  }

  protected setSort(key: keyof Query): void {
    const cur = this.sortBy();
    const dir: 'asc' | 'desc' = cur.key === key && cur.dir === 'desc' ? 'asc' : 'desc';
    this.sortBy.set({ key, dir });
  }

  protected toggle(id: string): void {
    const next = new Set(this.selected());
    if (next.has(id)) next.delete(id);
    else next.add(id);
    this.selected.set(next);
  }

  protected toggleAll(): void {
    const cur = this.selected();
    const list = this.filtered();
    if (cur.size === list.length) {
      this.selected.set(new Set());
    } else {
      this.selected.set(new Set(list.map((q) => q.query_id)));
    }
  }

  protected open(q: Query): void {
    this.#drawer.showQuery(q);
  }

  protected input(e: Event): string {
    const t = e.target as HTMLInputElement | HTMLSelectElement;
    return t.value;
  }

  protected relative(iso: string): string {
    return relativeTime(iso);
  }
}
