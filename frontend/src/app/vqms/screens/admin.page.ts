import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { Icon } from '../ui/icon';
import { Mono } from '../ui/mono';
import { Avatar } from '../ui/avatar';
import { HealthDot } from '../ui/health-dot';
import { Toggle } from '../ui/toggle';
import { EndpointsButton } from '../ui/endpoints-button';
import { EndpointsDrawer } from '../ui/endpoints-drawer';
import { FEATURE_FLAGS, INTEGRATIONS, USERS } from '../data/mock-data';
import { ENDPOINTS_ADMIN } from '../data/endpoints';
import { RoleService } from '../services/role.service';

type Tab = 'integrations' | 'users' | 'feature flags';

@Component({
  selector: 'vq-admin-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Icon, Mono, Avatar, HealthDot, Toggle, EndpointsButton, EndpointsDrawer],
  template: `
    <div class="p-6 max-w-[1600px] mx-auto fade-up">
      <div class="flex items-center justify-between mb-4">
        <div>
          <div class="ink" style="font-size:20px; font-weight:600; letter-spacing:-.02em;">Admin</div>
          <div class="muted mt-1" style="font-size:12.5px;">
            System health · users &amp; roles · feature flags
          </div>
        </div>
        <div class="flex items-center gap-2">
          <vq-endpoints-button (clicked)="endpointsOpen.set(true)" />
        </div>
      </div>

      <vq-endpoints-drawer
        [open]="endpointsOpen()"
        title="Admin · backend contract"
        subtitle="src/api/routes/admin.py"
        [endpoints]="endpoints"
        [role]="role.role()"
        (closed)="endpointsOpen.set(false)"
      />

      <div class="border-b hairline flex items-center mb-4">
        @for (t of tabs(); track t) {
          <span class="tab" [class.active]="tab() === t" (click)="tab.set(t)">
            {{ titleCase(t) }}
          </span>
        }
      </div>

      @if (tab() === 'integrations') {
        <div class="grid grid-cols-2 gap-3">
          @for (i of integrations; track i.name) {
            <div class="panel p-4" style="border-radius:4px;">
              <div class="flex items-start justify-between mb-2">
                <div class="flex items-center gap-2">
                  <vq-health-dot [status]="i.status" />
                  <span class="ink" style="font-size:13.5px; font-weight:600;">{{ i.name }}</span>
                  <span class="chip mono" style="font-size:10px;">{{ i.kind }}</span>
                </div>
                <vq-mono cssClass="muted" [size]="11">{{ i.region }}</vq-mono>
              </div>
              <div class="muted" style="font-size:11.5px;">{{ i.note }}</div>
              <div class="grid grid-cols-3 gap-3 mt-3 pt-3 border-t hairline">
                <div>
                  <div class="muted uppercase" style="font-size:9.5px; letter-spacing:.04em;">Status</div>
                  <span
                    style="font-size:12px; font-weight:600;"
                    [style.color]="statusColor(i.status)"
                    >{{ i.status.toUpperCase() }}</span
                  >
                </div>
                <div>
                  <div class="muted uppercase" style="font-size:9.5px; letter-spacing:.04em;">Latency p50</div>
                  <vq-mono [size]="14" [weight]="600">{{ i.latency_ms ? i.latency_ms + 'ms' : '—' }}</vq-mono>
                </div>
                <div>
                  <div class="muted uppercase" style="font-size:9.5px; letter-spacing:.04em;">Errors (1h)</div>
                  <vq-mono [size]="14" [weight]="600">{{ i.status === 'degraded' ? '14' : '0' }}</vq-mono>
                </div>
              </div>
            </div>
          }
        </div>
      }

      @if (tab() === 'users') {
        <div class="panel" style="border-radius:4px; overflow:hidden;">
          <div class="p-3 border-b hairline flex items-center justify-between">
            <input placeholder="Search users…" style="width:280px;" />
            @if (caps().manageUsers) {
              <button class="btn btn-primary"><vq-icon name="user-plus" [size]="13" /> Invite</button>
            }
          </div>
          <table class="vqms-table">
            <thead>
              <tr>
                <th>User</th><th>Email</th><th>Role</th><th>Status</th><th>Last active</th><th></th>
              </tr>
            </thead>
            <tbody>
              @for (u of users; track u.email) {
                <tr>
                  <td>
                    <div class="flex items-center gap-2">
                      <vq-avatar [name]="u.name" [size]="28" />
                      <div class="ink" style="font-size:13px; font-weight:500;">{{ u.name }}</div>
                    </div>
                  </td>
                  <td><vq-mono>{{ u.email }}</vq-mono></td>
                  <td>
                    <span
                      class="chip"
                      [style.color]="u.role === 'Admin' ? 'var(--accent)' : 'var(--ink-2)'"
                      [style.border-color]="u.role === 'Admin' ? 'var(--accent)' : 'var(--line-strong)'"
                      >{{ u.role }}</span
                    >
                  </td>
                  <td>
                    <span class="inline-flex items-center gap-1.5" style="font-size:12px;">
                      <span
                        [style.width.px]="6"
                        [style.height.px]="6"
                        [style.border-radius]="'999px'"
                        [style.background]="
                          u.status === 'online'
                            ? 'var(--ok)'
                            : u.status === 'away'
                              ? 'var(--warn)'
                              : 'var(--subtle)'
                        "
                      ></span>
                      {{ u.status }}
                    </span>
                  </td>
                  <td><vq-mono cssClass="muted">{{ u.last_active }}</vq-mono></td>
                  <td><button class="btn btn-ghost"><vq-icon name="more-horizontal" [size]="13" /></button></td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      }

      @if (tab() === 'feature flags') {
        <div class="panel" style="border-radius:4px; overflow:hidden;">
          <table class="vqms-table">
            <thead>
              <tr><th>Flag</th><th>Scope</th><th>State</th><th>Last changed</th></tr>
            </thead>
            <tbody>
              @for (f of flags; track f.key) {
                <tr>
                  <td><vq-mono [color]="'var(--ink)'" [weight]="500">{{ f.key }}</vq-mono></td>
                  <td><span class="chip">{{ f.scope }}</span></td>
                  <td><vq-toggle [on]="f.on" [disabled]="!caps().toggleFlags" /></td>
                  <td><vq-mono cssClass="muted">{{ f.changed }}</vq-mono></td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      }
    </div>
  `,
})
export class AdminPage {
  readonly #role = inject(RoleService);
  protected readonly role = this.#role;

  protected readonly integrations = INTEGRATIONS;
  protected readonly users = USERS;
  protected readonly flags = FEATURE_FLAGS;

  protected readonly tab = signal<Tab>('integrations');
  protected readonly caps = this.#role.caps;
  protected readonly endpointsOpen = signal(false);
  protected readonly endpoints = ENDPOINTS_ADMIN;

  protected readonly tabs = computed<readonly Tab[]>(() => {
    const out: Tab[] = ['integrations'];
    if (this.caps().manageUsers) out.push('users');
    if (this.caps().toggleFlags) out.push('feature flags');
    return out;
  });

  protected titleCase(s: string): string {
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  protected statusColor(s: string): string {
    if (s === 'healthy') return 'var(--ok)';
    if (s === 'degraded') return 'var(--warn)';
    if (s === 'down') return 'var(--bad)';
    return 'var(--muted)';
  }
}
