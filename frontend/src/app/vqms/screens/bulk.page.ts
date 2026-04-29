import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { Icon } from '../ui/icon';
import { Mono } from '../ui/mono';
import { ConfidenceBar } from '../ui/confidence-bar';
import { Status } from '../ui/status';
import { PathBadge } from '../ui/path-badge';
import { SectionHead } from '../ui/section-head';
import { EndpointsButton } from '../ui/endpoints-button';
import { EndpointsDrawer } from '../ui/endpoints-drawer';
import { ENDPOINTS_BULK } from '../data/endpoints';
import { QueriesStore } from '../services/queries.store';
import { RoleService } from '../services/role.service';

interface Action {
  readonly k: string;
  readonly icon: string;
  readonly label: string;
  readonly desc: string;
}

const ACTIONS: readonly Action[] = [
  { k: 'approve', icon: 'check', label: 'Approve drafts', desc: 'Send queued resolutions' },
  { k: 'reroute', icon: 'route', label: 'Reroute to team', desc: 'Change assigned_team' },
  {
    k: 'escalate',
    icon: 'alert-triangle',
    label: 'Escalate priority',
    desc: 'P3 → P2 / P2 → P1',
  },
  { k: 'close', icon: 'archive', label: 'Force close', desc: 'Mark RESOLVED + auto‑close' },
  { k: 'tag', icon: 'tag', label: 'Add tag', desc: 'Apply a label across selection' },
];

@Component({
  selector: 'vq-bulk-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Icon, Mono, ConfidenceBar, Status, PathBadge, SectionHead, EndpointsButton, EndpointsDrawer],
  template: `
    <div class="p-6 max-w-[1600px] mx-auto fade-up">
      <div class="flex items-center justify-between mb-5">
        <div>
          <div class="ink" style="font-size:20px; font-weight:600; letter-spacing:-.02em;">Bulk actions</div>
          <div class="muted mt-1" style="font-size:12.5px;">
            Apply an action to a filtered slice · preview before confirm
          </div>
        </div>
        <div class="flex items-center gap-2">
          <vq-endpoints-button (clicked)="endpointsOpen.set(true)" />
        </div>
      </div>

      <vq-endpoints-drawer
        [open]="endpointsOpen()"
        title="Bulk actions · backend contract"
        subtitle="proposed wrappers around queries.py + admin.py"
        [endpoints]="endpoints"
        [role]="role.role()"
        (closed)="endpointsOpen.set(false)"
      />

      <div class="grid grid-cols-12 gap-3">
        <div class="panel p-4 col-span-4" style="border-radius:4px;">
          <vq-section-head title="1. Pick action" />
          <div class="flex flex-col gap-2">
            @for (o of actions; track o.k) {
              <label
                class="flex items-start gap-3 p-3 rounded cursor-pointer"
                [style.background]="action() === o.k ? 'var(--accent-soft)' : 'transparent'"
                [style.border]="action() === o.k ? '1px solid var(--accent)' : '1px solid var(--line)'"
              >
                <input
                  type="radio"
                  [checked]="action() === o.k"
                  (change)="action.set(o.k)"
                  style="accent-color: var(--accent);"
                />
                <div>
                  <div class="ink" style="font-size:13px; font-weight:500;">
                    <vq-icon [name]="o.icon" [size]="12" cssClass="mr-1" />
                    {{ o.label }}
                  </div>
                  <div class="muted" style="font-size:11.5px;">{{ o.desc }}</div>
                </div>
              </label>
            }
          </div>
        </div>

        <div class="panel p-4 col-span-4" style="border-radius:4px;">
          <vq-section-head title="2. Filter selection" />
          <div class="flex flex-col gap-3 mt-1">
            <div>
              <div class="muted uppercase mb-1" style="font-size:10px; letter-spacing:.04em;">Status</div>
              <select [value]="filterStatus()" (change)="filterStatus.set(input($event))">
                @for (s of statuses; track s) {
                  <option>{{ s }}</option>
                }
              </select>
            </div>
            <div>
              <div class="muted uppercase mb-1" style="font-size:10px; letter-spacing:.04em;">Path</div>
              <select [value]="filterPath()" (change)="filterPath.set(input($event))">
                @for (p of paths; track p) {
                  <option>{{ p }}</option>
                }
              </select>
            </div>
            <div>
              <div class="muted uppercase mb-1" style="font-size:10px; letter-spacing:.04em;">Vendor tier</div>
              <select>
                <option>Any</option><option>PLATINUM</option><option>GOLD</option><option>SILVER</option><option>BRONZE</option>
              </select>
            </div>
            <div>
              <div class="muted uppercase mb-1" style="font-size:10px; letter-spacing:.04em;">Received</div>
              <select>
                <option>Last 24 hours</option><option>Last 7 days</option><option>Last 30 days</option>
              </select>
            </div>
          </div>
          <div class="mt-3 pt-3 border-t hairline">
            <vq-mono>{{ matched().length }}</vq-mono>
            <span class="muted text-[12px]">queries match</span>
          </div>
        </div>

        <div class="panel p-4 col-span-4" style="border-radius:4px;">
          <vq-section-head title="3. Confirm" />
          <div class="muted mb-3" style="font-size:12.5px;">
            You are about to <span class="ink" style="font-weight:500;">{{ action() }}</span> across
            <vq-mono>{{ matched().length }}</vq-mono> queries. This action will write to
            <vq-mono>audit.action_log</vq-mono> and may trigger downstream events.
          </div>
          <label class="flex items-center gap-2 mb-3" style="font-size:12px;">
            <input type="checkbox" style="accent-color: var(--accent);" />
            I understand this action cannot be undone.
          </label>
          <button class="btn btn-accent w-full justify-center">
            <vq-icon name="zap" [size]="13" /> Run on {{ matched().length }} queries
          </button>
          <button class="btn w-full justify-center mt-2">
            <vq-icon name="eye" [size]="13" /> Dry run
          </button>
        </div>
      </div>

      <div class="mt-3 panel" style="border-radius:4px; overflow:hidden;">
        <div class="p-3 border-b hairline">
          <vq-section-head
            title="Selection preview"
            [desc]="matched().length + ' queries match the filter above'"
          />
        </div>
        <table class="vqms-table">
          <thead>
            <tr>
              <th>Query</th><th>Vendor</th><th>Subject</th><th>Path</th><th>Status</th><th>Conf.</th>
            </tr>
          </thead>
          <tbody>
            @for (q of matched(); track q.query_id) {
              <tr>
                <td><vq-mono>{{ q.query_id }}</vq-mono></td>
                <td class="ink-2">{{ q.vendor_name }}</td>
                <td>
                  <div class="truncate" style="max-width: 320px;">{{ q.subject }}</div>
                </td>
                <td><vq-path-badge [letter]="q.processing_path" size="sm" /></td>
                <td><vq-status [value]="q.status" /></td>
                <td><vq-confidence-bar [value]="q.confidence" /></td>
              </tr>
            }
          </tbody>
        </table>
      </div>
    </div>
  `,
})
export class BulkPage {
  readonly #queries = inject(QueriesStore);
  protected readonly role = inject(RoleService);

  protected readonly endpointsOpen = signal(false);
  protected readonly endpoints = ENDPOINTS_BULK;

  protected readonly actions = ACTIONS;
  protected readonly statuses: readonly string[] = [
    'DRAFTING',
    'ROUTING',
    'ANALYZING',
    'AWAITING_RESOLUTION',
    'PAUSED',
  ];
  protected readonly paths: readonly string[] = ['A', 'B', 'C'];

  protected readonly action = signal<string>('approve');
  protected readonly filterStatus = signal<string>('DRAFTING');
  protected readonly filterPath = signal<string>('B');

  protected readonly matched = computed(() =>
    this.#queries
      .list()
      .filter(
        (q) => q.status === this.filterStatus() && q.processing_path === this.filterPath(),
      )
      .slice(0, 12),
  );

  protected input(e: Event): string {
    return (e.target as HTMLSelectElement).value;
  }
}
