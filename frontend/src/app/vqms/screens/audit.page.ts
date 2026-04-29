import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { Icon } from '../ui/icon';
import { Mono } from '../ui/mono';
import { EndpointsButton } from '../ui/endpoints-button';
import { EndpointsDrawer } from '../ui/endpoints-drawer';
import { AUDIT_LOG } from '../data/mock-data';
import { ENDPOINTS_AUDIT } from '../data/endpoints';
import { RoleService } from '../services/role.service';

type Tab = 'events' | 'anomalies';

interface Anomaly {
  readonly ts: string;
  readonly actor: string;
  readonly action: string;
  readonly target: string;
  readonly severity: 'low' | 'medium' | 'high';
  readonly score: number;
  readonly reason: string;
}

// Fixture data — would come from GET /audit/anomalies (Bedrock-flagged
// unusual actor/action pairs). Severity is bucketed from the model's score:
// score >= 0.8 → high, 0.5–0.8 → medium, < 0.5 → low.
const ANOMALIES: readonly Anomaly[] = [
  {
    ts: '2026-04-29 03:14:08',
    actor: 'svc-pipeline@hexaware.com',
    action: 'Bulk close (24 queries) outside business hours',
    target: 'queries.bulk',
    severity: 'high',
    score: 0.94,
    reason: 'Service account has never run bulk operations between 23:00–06:00 IST in 90d',
  },
  {
    ts: '2026-04-29 02:47:31',
    actor: 'n.shah@hexaware.com',
    action: 'Force-closed query without acknowledgment',
    target: 'VQ-2026-1840',
    severity: 'high',
    score: 0.87,
    reason: 'Reviewer skipped Quality Gate · vendor email never sent',
  },
  {
    ts: '2026-04-28 19:02:11',
    actor: 'k.tanaka@hexaware.com',
    action: 'Approved 18 drafts in 4 minutes',
    target: 'workflow.draft_responses',
    severity: 'medium',
    score: 0.71,
    reason: 'P95 approval latency for this user is 22s — burst suggests rubber-stamp',
  },
  {
    ts: '2026-04-28 16:33:55',
    actor: 'system',
    action: 'Confidence override 0.42 → 1.00',
    target: 'VQ-2026-1832',
    severity: 'medium',
    score: 0.68,
    reason: 'Override magnitude > 0.5 typically requires reviewer notes — none provided',
  },
  {
    ts: '2026-04-28 11:08:42',
    actor: 'a.verma@hexaware.com',
    action: 'Repeated read access to V-002 vendor record (47x)',
    target: 'vendors.V-002',
    severity: 'low',
    score: 0.43,
    reason: 'Above 3σ from per-user baseline · likely investigation, not exfil',
  },
];

@Component({
  selector: 'vq-audit-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Icon, Mono, EndpointsButton, EndpointsDrawer],
  template: `
    <div class="p-6 max-w-[1600px] mx-auto fade-up">
      <div class="flex items-center justify-between mb-4">
        <div>
          <div class="ink" style="font-size:20px; font-weight:600; letter-spacing:-.02em;">Audit log</div>
          <div class="muted mt-1" style="font-size:12.5px;">audit.action_log · all actor / system events · immutable</div>
        </div>
        <div class="flex items-center gap-2">
          <input placeholder="Search…" style="width:240px;" />
          <button class="btn"><vq-icon name="filter" [size]="13" /> Filter</button>
          <button class="btn"><vq-icon name="download" [size]="13" /> Export</button>
          <vq-endpoints-button (clicked)="endpointsOpen.set(true)" />
        </div>
      </div>

      <div class="border-b hairline flex items-center mb-4">
        <span class="tab" [class.active]="tab() === 'events'" (click)="tab.set('events')">
          <vq-icon name="scroll-text" [size]="12" cssClass="mr-1" /> Events
          <vq-mono cssClass="muted ml-1" [size]="10.5">{{ audit.length }}</vq-mono>
        </span>
        <span class="tab" [class.active]="tab() === 'anomalies'" (click)="tab.set('anomalies')">
          <vq-icon name="alert-triangle" [size]="12" cssClass="mr-1" /> Anomalies
          @if (anomalyCount() > 0) {
            <vq-mono cssClass="ml-1" [size]="10.5" [color]="'var(--bad)'" [weight]="600">{{
              anomalyCount()
            }}</vq-mono>
          }
        </span>
      </div>

      <vq-endpoints-drawer
        [open]="endpointsOpen()"
        title="Audit log · backend contract"
        subtitle="src/api/routes/audit.py"
        [endpoints]="endpoints"
        [role]="role.role()"
        (closed)="endpointsOpen.set(false)"
      />

      @if (tab() === 'events') {
        <div class="panel" style="border-radius:4px; overflow:hidden;">
          <table class="vqms-table">
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Target</th>
                <th>Note</th>
              </tr>
            </thead>
            <tbody>
              @for (a of audit; track a.ts + a.target + a.action) {
                <tr>
                  <td><vq-mono cssClass="muted">{{ a.ts }}</vq-mono></td>
                  <td>
                    @if (a.actor === 'system') {
                      <span class="chip mono" style="font-size:10.5px;">system</span>
                    } @else {
                      <vq-mono>{{ a.actor }}</vq-mono>
                    }
                  </td>
                  <td class="ink-2" style="font-size:12.5px;">{{ a.action }}</td>
                  <td>
                    @if (a.target === '—') {
                      <span class="subtle">—</span>
                    } @else {
                      <vq-mono [color]="'var(--accent)'">{{ a.target }}</vq-mono>
                    }
                  </td>
                  <td class="muted" style="font-size:12px;">{{ a.note }}</td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      } @else {
        <div class="mb-3 flex items-center gap-2 muted" style="font-size:12px;">
          <vq-icon name="sparkles" [size]="12" cssClass="text-accent" />
          AI‑flagged unusual actor / action pairs · model: Bedrock anomaly scorer · refreshed every 15m
          <span class="flex-1"></span>
          <span class="chip" style="color: var(--bad); border-color: var(--bad);">
            <vq-mono [size]="10.5">{{ counts().high }}</vq-mono> high
          </span>
          <span class="chip" style="color: var(--warn); border-color: var(--warn);">
            <vq-mono [size]="10.5">{{ counts().medium }}</vq-mono> medium
          </span>
          <span class="chip">
            <vq-mono [size]="10.5">{{ counts().low }}</vq-mono> low
          </span>
        </div>

        <div class="panel" style="border-radius:4px; overflow:hidden;">
          <table class="vqms-table">
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Target</th>
                <th>Severity</th>
                <th>Why flagged</th>
                <th style="width:80px;"></th>
              </tr>
            </thead>
            <tbody>
              @for (a of anomalies; track a.ts + a.target) {
                <tr>
                  <td><vq-mono cssClass="muted">{{ a.ts }}</vq-mono></td>
                  <td>
                    @if (a.actor === 'system' || a.actor.startsWith('svc-')) {
                      <span class="chip mono" style="font-size:10.5px;">{{ a.actor }}</span>
                    } @else {
                      <vq-mono>{{ a.actor }}</vq-mono>
                    }
                  </td>
                  <td class="ink-2" style="font-size:12.5px;">{{ a.action }}</td>
                  <td><vq-mono [color]="'var(--accent)'">{{ a.target }}</vq-mono></td>
                  <td>
                    <span class="chip" [style]="severityStyle(a.severity)">
                      <vq-mono [size]="10.5" [weight]="600">{{ a.severity }}</vq-mono>
                      <span class="muted ml-1" style="font-size:10px;">{{ a.score.toFixed(2) }}</span>
                    </span>
                  </td>
                  <td class="muted" style="font-size:12px;">{{ a.reason }}</td>
                  <td>
                    <button class="btn btn-ghost" title="Dismiss anomaly">
                      <vq-icon name="x" [size]="12" />
                    </button>
                  </td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      }
    </div>
  `,
})
export class AuditPage {
  protected readonly audit = AUDIT_LOG;
  protected readonly anomalies = ANOMALIES;
  protected readonly role = inject(RoleService);
  protected readonly endpointsOpen = signal(false);
  protected readonly endpoints = ENDPOINTS_AUDIT;
  protected readonly tab = signal<Tab>('events');

  protected anomalyCount(): number {
    return this.anomalies.length;
  }

  protected counts(): { high: number; medium: number; low: number } {
    return this.anomalies.reduce(
      (acc, a) => {
        acc[a.severity] += 1;
        return acc;
      },
      { high: 0, medium: 0, low: 0 },
    );
  }

  protected severityStyle(s: Anomaly['severity']): string {
    if (s === 'high') {
      return 'color: var(--bad); border-color: var(--bad); background: color-mix(in oklch, var(--bad) 8%, var(--panel));';
    }
    if (s === 'medium') {
      return 'color: var(--warn); border-color: var(--warn); background: color-mix(in oklch, var(--warn) 8%, var(--panel));';
    }
    return 'color: var(--ink-2); border-color: var(--line-strong);';
  }
}
