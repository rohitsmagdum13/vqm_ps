import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { Icon } from './icon';
import { Mono } from './mono';
import type { EndpointSpec, EndpointStatus, HttpVerb } from '../data/endpoints';

const VERB_COLOR: Record<HttpVerb, string> = {
  GET: 'var(--info)',
  POST: 'var(--ok)',
  PATCH: 'var(--accent)',
  PUT: 'var(--accent)',
  DELETE: 'var(--bad)',
};

function verbColor(method: HttpVerb, status: EndpointStatus): string {
  if (method === 'GET') return VERB_COLOR.GET;
  if (method === 'DELETE') return VERB_COLOR.DELETE;
  return status === 'new' ? 'var(--accent)' : 'var(--ok)';
}

@Component({
  selector: 'vq-endpoints-drawer',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Icon, Mono],
  template: `
    @if (open()) {
      <div
        class="fixed inset-0 z-40"
        style="background: rgba(0,0,0,.32);"
        (click)="closed.emit()"
      >
        <div
          class="absolute right-0 top-0 bottom-0 panel fade-up overflow-auto"
          style="width: 720px; max-width: 92vw; border-left: 1px solid var(--line-strong);"
          (click)="$event.stopPropagation()"
        >
          <div
            class="flex items-center justify-between px-6 py-4 border-b hairline"
            style="position: sticky; top: 0; background: var(--panel); z-index: 1;"
          >
            <div>
              <div class="ink" style="font-size:16px; font-weight:600;">{{ title() }}</div>
              <vq-mono [color]="'var(--muted)'" [size]="11">{{ subtitle() }}</vq-mono>
            </div>
            <div class="flex items-center gap-2">
              <span class="chip" [style]="roleChipStyle()">
                <vq-icon name="user" [size]="10" /> {{ role() }} scope
              </span>
              <button class="btn btn-ghost" (click)="closed.emit()" title="Close">
                <vq-icon name="x" [size]="14" />
              </button>
            </div>
          </div>

          <div class="px-6 py-4">
            @if (existing().length > 0) {
              <div
                class="muted uppercase tracking-wider mb-2 flex items-center gap-2"
                style="font-size:10px; font-weight:600;"
              >
                Already in codebase
                <span
                  class="mono"
                  style="font-size:10px; padding:0 6px; background:var(--bg); color:var(--ok); border-radius:999px;"
                  >{{ existing().length }}</span
                >
              </div>
              <table class="vqms-table">
                <thead>
                  <tr>
                    <th style="width:70px;">Verb</th>
                    <th>Path</th>
                    <th>Source</th>
                    <th>Notes</th>
                  </tr>
                </thead>
                <tbody>
                  @for (e of existing(); track e.path + e.method) {
                    <tr style="cursor:default;">
                      <td>
                        <vq-mono [weight]="600" [color]="verbColor(e.method, e.status)">{{ e.method }}</vq-mono>
                      </td>
                      <td>
                        <vq-mono cssClass="ink" [weight]="500">{{ e.path }}</vq-mono>
                      </td>
                      <td class="muted" style="font-size:11.5px;">{{ e.source }}</td>
                      <td class="muted" style="font-size:11.5px;">{{ e.note }}</td>
                    </tr>
                  }
                </tbody>
              </table>
            }

            @if (proposed().length > 0) {
              <div
                class="muted uppercase tracking-wider mb-2 mt-6 flex items-center gap-2"
                style="font-size:10px; font-weight:600;"
              >
                Proposed new
                <span
                  class="mono"
                  style="font-size:10px; padding:0 6px; background:var(--accent-soft); color:var(--accent); border-radius:999px;"
                  >{{ proposed().length }}</span
                >
              </div>
              <table class="vqms-table">
                <thead>
                  <tr>
                    <th style="width:70px;">Verb</th>
                    <th>Path</th>
                    <th>Wraps / depends on</th>
                    <th>Notes</th>
                  </tr>
                </thead>
                <tbody>
                  @for (e of proposed(); track e.path + e.method) {
                    <tr style="cursor:default;">
                      <td>
                        <vq-mono [weight]="600" [color]="verbColor(e.method, e.status)">{{ e.method }}</vq-mono>
                      </td>
                      <td>
                        <vq-mono cssClass="ink" [weight]="500">{{ e.path }}</vq-mono>
                      </td>
                      <td class="muted" style="font-size:11.5px;">{{ e.source || '—' }}</td>
                      <td class="muted" style="font-size:11.5px;">{{ e.note }}</td>
                    </tr>
                  }
                </tbody>
              </table>
            }

            <div
              class="mt-6 panel"
              style="background: var(--bg); padding: 12px; border-radius: 4px;"
            >
              <div class="muted" style="font-size:11px; line-height:1.6;">
                <vq-mono [color]="'var(--ink-2)'">Authorization: Bearer &lt;jwt&gt;</vq-mono>
                · 8h TTL · role claims gate every route. All write operations emit a
                <vq-mono [color]="'var(--ink-2)'">workflow.audit_events</vq-mono> row and an
                <vq-mono [color]="'var(--ink-2)'">Amazon EventBridge</vq-mono> event for
                downstream consumers.
              </div>
            </div>
          </div>
        </div>
      </div>
    }
  `,
})
export class EndpointsDrawer {
  readonly open = input.required<boolean>();
  readonly title = input<string>('Backend endpoints this UI calls');
  readonly subtitle = input<string>('handoff reference · src/api/routes/*');
  readonly endpoints = input.required<readonly EndpointSpec[]>();
  readonly role = input<string>('Admin');
  readonly closed = output<void>();

  readonly existing = computed(() => this.endpoints().filter((e) => e.status === 'exists'));
  readonly proposed = computed(() => this.endpoints().filter((e) => e.status === 'new'));

  readonly roleChipStyle = computed(() => {
    const r = this.role();
    if (r === 'Admin') {
      return 'background: var(--accent-soft); color: var(--accent); border-color: transparent;';
    }
    if (r === 'Reviewer') {
      return 'background: color-mix(in oklch, var(--info) 12%, var(--panel)); color: var(--info); border-color: transparent;';
    }
    return 'background: var(--bg); color: var(--ink-2); border-color: transparent;';
  });

  readonly verbColor = verbColor;
}
