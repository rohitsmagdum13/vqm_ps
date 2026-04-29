import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { Icon } from '../ui/icon';
import { Mono } from '../ui/mono';
import { Avatar } from '../ui/avatar';
import { Tier } from '../ui/tier';
import { Status } from '../ui/status';
import { Priority } from '../ui/priority';
import { PathBadge } from '../ui/path-badge';
import { ConfidenceBar } from '../ui/confidence-bar';
import { SlaBar } from '../ui/sla-bar';
import { Drawer } from '../ui/drawer';
import { SectionHead } from '../ui/section-head';
import {
  AI_SUGGESTED,
  AUDIT_LOG,
  SAMPLE_THREAD,
  SOURCES_USED,
  relativeTime,
} from '../data/mock-data';
import { DrawerService } from '../services/drawer.service';
import { RoleService } from '../services/role.service';
import { VendorsStore } from '../services/vendors.store';

type Tab = 'thread' | 'ai-response' | 'metadata' | 'audit';

const TABS: readonly Tab[] = ['thread', 'ai-response', 'metadata', 'audit'];

const TAB_LABELS: Readonly<Record<Tab, string>> = {
  thread: 'Thread',
  'ai-response': 'AI response',
  metadata: 'Pipeline metadata',
  audit: 'Audit trail',
};

const STATE_NODES: readonly string[] = [
  'entry',
  'context_loading',
  'query_analysis',
  'confidence_check',
  'routing',
  'kb_search',
  'path_decision',
  'resolution',
  'quality_gate',
  'delivery',
];

@Component({
  selector: 'vq-query-detail-drawer',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    Icon,
    Mono,
    Avatar,
    Tier,
    Status,
    Priority,
    PathBadge,
    ConfidenceBar,
    SlaBar,
    Drawer,
    SectionHead,
  ],
  template: `
    <vq-drawer [open]="hasQuery()" [width]="920" (closed)="close()">
      @if (q(); as query) {
        <div
          class="border-b hairline px-6 py-4 sticky top-0 bg-panel z-10"
          style="background: var(--panel);"
        >
          <div class="flex items-start justify-between gap-4">
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 mb-2">
                <vq-priority [p]="query.priority" />
                <vq-mono [color]="'var(--ink)'" [weight]="600" [size]="13">{{ query.query_id }}</vq-mono>
                <vq-status [value]="query.status" />
                <vq-path-badge [letter]="query.processing_path" size="sm" />
                @if (query.ticket_id) {
                  <span class="chip mono"><vq-icon name="link-2" [size]="10" /> {{ query.ticket_id }}</span>
                }
              </div>
              <div class="ink" style="font-size:17px; font-weight:600; letter-spacing:-.01em;">{{ query.subject }}</div>
              <div
                class="muted mt-1.5 flex items-center gap-2 flex-wrap"
                style="font-size:12px;"
              >
                <span>{{ vendor()?.name }}</span>
                @if (vendor()) {
                  <vq-tier [tier]="vendor()!.tier" />
                }
                <span>·</span>
                <vq-mono>{{ query.vendor_id }}</vq-mono>
                <span>·</span>
                <span>{{ query.intent }}</span>
                <span>·</span>
                <vq-mono>{{ relative(query.received_at) }}</vq-mono>
              </div>
            </div>
            <div class="flex items-center gap-1.5">
              <button class="btn btn-ghost" title="Copy link"><vq-icon name="link" [size]="13" /></button>
              <button class="btn btn-ghost" title="More"><vq-icon name="more-horizontal" [size]="13" /></button>
              <button class="btn btn-ghost" (click)="close()" title="Close">
                <vq-icon name="x" [size]="14" />
              </button>
            </div>
          </div>

          <div class="flex items-center mt-4 -mb-px">
            @for (t of tabs; track t) {
              <span class="tab" [class.active]="tab() === t" (click)="tab.set(t)">
                {{ tabLabel(t) }}
                @if (t === 'thread') {
                  <vq-mono cssClass="ml-1.5 muted">2</vq-mono>
                }
                @if (t === 'ai-response') {
                  <vq-mono cssClass="ml-1.5 muted">{{ query.confidence.toFixed(2) }}</vq-mono>
                }
              </span>
            }
          </div>
        </div>

        <div class="px-6 py-5 grid grid-cols-3 gap-5">
          <div class="col-span-2">
            @if (tab() === 'thread') {
              <div class="flex flex-col gap-3">
                @for (m of thread; track m.ts) {
                  @if (m.direction === 'system') {
                    <div class="flex items-center gap-2 py-2">
                      <span style="width:6px; height:6px; background: var(--accent); border-radius:999px;"></span>
                      <vq-mono cssClass="muted" [size]="11">{{ m.ts }}</vq-mono>
                      <span class="muted" style="font-size:11.5px;">{{ m.note }}</span>
                    </div>
                  } @else {
                    <div class="panel p-4" style="border-radius:4px;">
                      <div class="flex items-center justify-between mb-2">
                        <div class="flex items-center gap-2">
                          <vq-avatar name="Marcus Holloway" [size]="28" />
                          <div>
                            <div class="ink" style="font-size:12.5px; font-weight:500;">Marcus Holloway</div>
                            <vq-mono cssClass="muted" [size]="10.5">{{ m.from }}</vq-mono>
                          </div>
                        </div>
                        <vq-mono cssClass="muted" [size]="11">{{ m.ts }}</vq-mono>
                      </div>
                      <div
                        class="ink-2"
                        style="font-size:13px; line-height:1.6; white-space: pre-wrap;"
                      >{{ m.body }}</div>
                      @if (m.attachments && m.attachments.length > 0) {
                        <div class="mt-3 pt-3 border-t hairline flex items-center gap-2 flex-wrap">
                          @for (a of m.attachments; track a.name) {
                            <span class="chip" style="padding:4px 10px;">
                              <vq-icon name="paperclip" [size]="11" /> {{ a.name }}
                              <span class="muted">· {{ a.size }}</span>
                            </span>
                          }
                        </div>
                      }
                    </div>
                  }
                }
              </div>
            }

            @if (tab() === 'ai-response') {
              <div>
                <div
                  class="panel p-4 mb-3"
                  style="border-radius:4px; border-color: var(--accent); border-width:1px;"
                >
                  <div class="flex items-center justify-between mb-3">
                    <div class="flex items-center gap-2">
                      <vq-icon name="sparkles" [size]="14" cssClass="text-accent" />
                      <span class="ink" style="font-size:13px; font-weight:600;">Suggested response</span>
                      <span class="chip mono" style="font-size:10px;">claude‑sonnet‑3.5</span>
                    </div>
                    <button class="btn btn-ghost" (click)="toggleEdit()">
                      <vq-icon [name]="draftEdit() ? 'check' : 'pencil'" [size]="13" />
                      {{ draftEdit() ? 'Done' : 'Edit' }}
                    </button>
                  </div>
                  @if (draftEdit()) {
                    <textarea
                      [value]="draft()"
                      (input)="draft.set(input($event))"
                      style="width:100%; min-height:240px; font-family:inherit; font-size:13px; line-height:1.55;"
                    ></textarea>
                  } @else {
                    <div
                      class="ink-2"
                      style="font-size:13px; line-height:1.65; white-space:pre-wrap;"
                    >{{ draft() }}</div>
                  }
                  <div
                    class="grid grid-cols-3 gap-3 mt-4 pt-4 border-t hairline"
                    style="font-size:11.5px;"
                  >
                    <div>
                      <div class="muted uppercase mb-1" style="font-size:10px; letter-spacing:.04em;">Confidence</div>
                      <vq-confidence-bar [value]="query.confidence" />
                    </div>
                    <div>
                      <div class="muted uppercase mb-1" style="font-size:10px; letter-spacing:.04em;">KB Match (cosine)</div>
                      <vq-confidence-bar [value]="query.kb_match" [threshold]="0.80" />
                    </div>
                    <div>
                      <div class="muted uppercase mb-1" style="font-size:10px; letter-spacing:.04em;">Quality Gate</div>
                      <span class="chip" style="color: var(--ok); border-color: var(--ok);">
                        <vq-icon name="check" [size]="11" /> 7/7 passed
                      </span>
                    </div>
                  </div>
                </div>

                <div class="panel p-4" style="border-radius:4px;">
                  <vq-section-head title="Sources used" desc="Retrieved from memory.embedding_index" />
                  @for (s of sources; track s.kb_id; let last = $last) {
                    <div
                      class="flex items-center gap-3 py-2 border-b hairline"
                      [class.last:border-0]="last"
                    >
                      <vq-icon name="book-open" [size]="14" cssClass="muted" />
                      <div class="flex-1">
                        <div class="ink-2" style="font-size:12.5px;">{{ s.title }}</div>
                        <vq-mono cssClass="muted" [size]="10.5">{{ s.kb_id }}</vq-mono>
                      </div>
                      <vq-mono>{{ s.cosine.toFixed(2) }}</vq-mono>
                    </div>
                  }
                </div>
              </div>
            }

            @if (tab() === 'metadata') {
              <div class="panel p-5" style="border-radius:4px;">
                <div class="grid grid-cols-2 gap-x-6 gap-y-3" style="font-size:12.5px;">
                  <div class="flex items-center justify-between gap-3 py-1.5 border-b hairline">
                    <span class="muted" style="font-size:11.5px;">execution_id</span>
                    <vq-mono>{{ query.execution_id }}</vq-mono>
                  </div>
                  <div class="flex items-center justify-between gap-3 py-1.5 border-b hairline">
                    <span class="muted" style="font-size:11.5px;">correlation_id</span>
                    <vq-mono>{{ query.correlation_id }}</vq-mono>
                  </div>
                  <div class="flex items-center justify-between gap-3 py-1.5 border-b hairline">
                    <span class="muted" style="font-size:11.5px;">source</span>
                    <span class="ink-2">{{ query.source }}</span>
                  </div>
                  <div class="flex items-center justify-between gap-3 py-1.5 border-b hairline">
                    <span class="muted" style="font-size:11.5px;">received_at</span>
                    <vq-mono>{{ query.received_at }}</vq-mono>
                  </div>
                  <div class="flex items-center justify-between gap-3 py-1.5 border-b hairline">
                    <span class="muted" style="font-size:11.5px;">processing_path</span>
                    <vq-path-badge [letter]="query.processing_path" size="sm" />
                  </div>
                  <div class="flex items-center justify-between gap-3 py-1.5 border-b hairline">
                    <span class="muted" style="font-size:11.5px;">assigned_team</span>
                    <span class="ink-2">{{ query.assigned_team }}</span>
                  </div>
                  <div class="flex items-center justify-between gap-3 py-1.5 border-b hairline">
                    <span class="muted" style="font-size:11.5px;">ticket_id</span>
                    @if (query.ticket_id) {
                      <vq-mono>{{ query.ticket_id }}</vq-mono>
                    } @else {
                      <span class="subtle">—</span>
                    }
                  </div>
                  <div class="flex items-center justify-between gap-3 py-1.5 border-b hairline">
                    <span class="muted" style="font-size:11.5px;">confidence</span>
                    <vq-mono>{{ query.confidence }}</vq-mono>
                  </div>
                  <div class="flex items-center justify-between gap-3 py-1.5 border-b hairline">
                    <span class="muted" style="font-size:11.5px;">kb_cosine</span>
                    <vq-mono>{{ query.kb_match }}</vq-mono>
                  </div>
                  <div class="flex items-center justify-between gap-3 py-1.5 border-b hairline">
                    <span class="muted" style="font-size:11.5px;">sla_deadline</span>
                    @if (query.sla_pct) {
                      <vq-mono>{{ query.sla_deadline_min }}m left ({{ query.sla_pct }}%)</vq-mono>
                    } @else {
                      <span class="subtle">—</span>
                    }
                  </div>
                </div>

                <div class="mt-5 pt-4 border-t hairline">
                  <div class="muted uppercase mb-3" style="font-size:10.5px; letter-spacing:.04em;">
                    State machine trace
                  </div>
                  <div class="flex items-center gap-1.5 flex-wrap mono" style="font-size:11px;">
                    @for (n of stateNodes; track n; let i = $index, last = $last) {
                      <span
                        class="chip"
                        [style.background]="
                          query.processing_path === 'C' && i >= 4
                            ? 'var(--bg)'
                            : 'color-mix(in oklch, var(--ok) 12%, var(--panel))'
                        "
                        [style.color]="
                          query.processing_path === 'C' && i >= 4 ? 'var(--muted)' : 'var(--ok)'
                        "
                        [style.border-color]="'transparent'"
                      >{{ n }}</span>
                      @if (!last) {
                        <vq-icon name="chevron-right" [size]="10" cssClass="subtle" />
                      }
                    }
                  </div>
                </div>
              </div>
            }

            @if (tab() === 'audit') {
              <div class="panel" style="border-radius:4px;">
                @for (a of auditFor(query); track $index; let last = $last) {
                  <div
                    class="flex items-start gap-3 px-4 py-3 border-b hairline"
                    [class.last:border-0]="last"
                  >
                    <vq-mono cssClass="muted" [size]="11" style="min-width:130px;">{{ a.ts }}</vq-mono>
                    <div class="flex-1">
                      <div class="ink-2" style="font-size:12.5px;">{{ a.action }}</div>
                      <div class="muted" style="font-size:11px;">{{ a.note }}</div>
                    </div>
                    <vq-mono cssClass="muted" [size]="11">{{ a.actor }}</vq-mono>
                  </div>
                }
              </div>
            }
          </div>

          <div class="col-span-1 flex flex-col gap-4">
            <div class="panel p-4" style="border-radius:4px;">
              <div class="flex items-center justify-between mb-3">
                <div class="ink" style="font-size:12.5px; font-weight:600;">Actions</div>
                <vq-mono cssClass="muted" [size]="10">as {{ role() }}</vq-mono>
              </div>
              <div class="flex flex-col gap-2">
                @if (caps().approve) {
                  <button class="btn btn-accent justify-center">
                    <vq-icon name="send" [size]="13" /> Approve &amp; send
                  </button>
                  <button class="btn justify-center">
                    <vq-icon name="pencil" [size]="13" /> Edit &amp; send
                  </button>
                }
                @if (caps().reroute) {
                  <button class="btn justify-center">
                    <vq-icon name="route" [size]="13" /> Reroute
                  </button>
                }
                @if (caps().escalate) {
                  <button class="btn justify-center">
                    <vq-icon name="alert-triangle" [size]="13" /> Escalate
                  </button>
                }
                @if (caps().approve) {
                  <button class="btn justify-center" style="color: var(--bad);">
                    <vq-icon name="x-circle" [size]="13" /> Reject draft
                  </button>
                }
                @if (!caps().approve && !caps().reroute && !caps().escalate) {
                  <div class="muted" style="font-size:12px;">
                    <vq-icon name="lock" [size]="11" cssClass="inline-block mr-1" />
                    Read-only access for this query.
                  </div>
                }
              </div>
            </div>

            @if (vendor(); as v) {
              <div class="panel p-4" style="border-radius:4px;">
                <div class="flex items-center justify-between mb-3">
                  <div class="ink" style="font-size:12.5px; font-weight:600;">Vendor</div>
                  <button class="btn btn-ghost"><vq-icon name="external-link" [size]="12" /></button>
                </div>
                <div class="flex items-center gap-2 mb-3">
                  <vq-avatar [name]="v.name" [size]="36" />
                  <div>
                    <div class="ink" style="font-size:13px; font-weight:500;">{{ v.name }}</div>
                    <div class="flex items-center gap-1.5 mt-0.5">
                      <vq-tier [tier]="v.tier" />
                      <vq-mono cssClass="muted" [size]="10.5">{{ v.vendor_id }}</vq-mono>
                    </div>
                  </div>
                </div>
                <div class="grid grid-cols-2 gap-x-3 gap-y-2" style="font-size:11.5px;">
                  <div>
                    <div class="muted uppercase mb-0.5" style="font-size:9.5px; letter-spacing:.06em;">Category</div>
                    <div class="ink-2" style="font-size:12px;">{{ v.category }}</div>
                  </div>
                  <div>
                    <div class="muted uppercase mb-0.5" style="font-size:9.5px; letter-spacing:.06em;">Tier SLA</div>
                    <div class="ink-2" style="font-size:12px;">{{ v.sla_response_hours }}h / {{ v.sla_resolution_days }}d</div>
                  </div>
                  <div>
                    <div class="muted uppercase mb-0.5" style="font-size:9.5px; letter-spacing:.06em;">Open queries</div>
                    <div class="ink-2" style="font-size:12px;">{{ v.open_queries }} ({{ v.p1_open }} P1)</div>
                  </div>
                  <div>
                    <div class="muted uppercase mb-0.5" style="font-size:9.5px; letter-spacing:.06em;">Health</div>
                    <span
                      style="font-size:12px;"
                      [style.color]="
                        v.health > 85 ? 'var(--ok)' : v.health > 70 ? 'var(--warn)' : 'var(--bad)'
                      "
                      >{{ v.health }}/100</span
                    >
                  </div>
                  <div>
                    <div class="muted uppercase mb-0.5" style="font-size:9.5px; letter-spacing:.06em;">Onboarded</div>
                    <vq-mono [size]="12">{{ v.onboarded_date }}</vq-mono>
                  </div>
                  <div>
                    <div class="muted uppercase mb-0.5" style="font-size:9.5px; letter-spacing:.06em;">Region</div>
                    <div class="ink-2" style="font-size:12px;">{{ v.city }}, {{ v.country }}</div>
                  </div>
                </div>
              </div>
            }

            @if (query.sla_pct) {
              <div class="panel p-4" style="border-radius:4px;">
                <div class="ink mb-2" style="font-size:12.5px; font-weight:600;">SLA</div>
                <vq-sla-bar [pct]="query.sla_pct" />
                <div class="muted mt-3" style="font-size:11px;">
                  {{ slaLabel(query.sla_pct) }} ·
                  <vq-mono>{{ query.sla_deadline_min }}m left</vq-mono>
                </div>
              </div>
            }
          </div>
        </div>
      }
    </vq-drawer>
  `,
})
export class QueryDetailDrawer {
  readonly #drawer = inject(DrawerService);
  readonly #role = inject(RoleService);
  readonly #vendors = inject(VendorsStore);

  protected readonly tabs = TABS;
  protected readonly thread = SAMPLE_THREAD;
  protected readonly sources = SOURCES_USED;
  protected readonly stateNodes = STATE_NODES;

  protected readonly q = this.#drawer.openQuery;
  protected readonly hasQuery = computed<boolean>(() => this.q() !== null);
  protected readonly tab = signal<Tab>('thread');
  protected readonly draftEdit = signal<boolean>(false);
  protected readonly draft = signal<string>(AI_SUGGESTED);
  protected readonly role = this.#role.role;
  protected readonly caps = this.#role.caps;

  protected readonly vendor = computed(() => {
    const id = this.q()?.vendor_id;
    return id ? this.#vendors.byId(id) : null;
  });

  protected close(): void {
    this.#drawer.closeQuery();
    this.tab.set('thread');
    this.draftEdit.set(false);
    this.draft.set(AI_SUGGESTED);
  }

  protected tabLabel(t: Tab): string {
    return TAB_LABELS[t];
  }

  protected toggleEdit(): void {
    this.draftEdit.set(!this.draftEdit());
  }

  protected input(e: Event): string {
    return (e.target as HTMLTextAreaElement).value;
  }

  protected relative(iso: string): string {
    return relativeTime(iso);
  }

  protected slaLabel(pct: number): string {
    if (pct >= 95) return 'Breached — L2 escalation';
    if (pct >= 85) return 'L1 escalation imminent';
    if (pct >= 70) return 'Warning fired';
    return 'On track';
  }

  protected auditFor(query: { query_id: string }): readonly typeof AUDIT_LOG[number][] {
    return AUDIT_LOG.filter(
      (a) => a.target === query.query_id || a.target === '—' || Math.random() > 0.5,
    ).slice(0, 6);
  }
}
