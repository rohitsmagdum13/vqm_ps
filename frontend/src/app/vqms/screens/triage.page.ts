import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { Icon } from '../ui/icon';
import { Mono } from '../ui/mono';
import { Priority } from '../ui/priority';
import { PathBadge } from '../ui/path-badge';
import { EndpointsButton } from '../ui/endpoints-button';
import { EndpointsDrawer } from '../ui/endpoints-drawer';
import { relativeTime } from '../data/mock-data';
import { ENDPOINTS_TRIAGE } from '../data/endpoints';
import { DrawerService } from '../services/drawer.service';
import { QueriesStore } from '../services/queries.store';
import { RoleService } from '../services/role.service';
import type { Query } from '../data/models';

@Component({
  selector: 'vq-triage-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Icon, Mono, Priority, PathBadge, EndpointsButton, EndpointsDrawer],
  template: `
    <div class="p-6 max-w-[1600px] mx-auto fade-up">
      <div class="flex items-center justify-between mb-5">
        <div>
          <div class="ink" style="font-size:20px; font-weight:600; letter-spacing:-.02em;">Triage queue</div>
          <div class="muted mt-1" style="font-size:12.5px;">
            Path C · low‑confidence cases awaiting reviewer decision
          </div>
        </div>
        <div class="flex items-center gap-2">
          <span class="chip"><vq-mono>{{ queue().length }}</vq-mono> pending</span>
          <button class="btn"><vq-icon name="users" [size]="13" /> Assign me</button>
          <vq-endpoints-button (clicked)="endpointsOpen.set(true)" />
        </div>
      </div>

      <vq-endpoints-drawer
        [open]="endpointsOpen()"
        title="Triage queue · backend contract"
        subtitle="src/api/routes/triage.py"
        [endpoints]="endpoints"
        [role]="role.role()"
        (closed)="endpointsOpen.set(false)"
      />

      <div class="grid grid-cols-2 gap-3">
        @for (q of queue(); track q.query_id) {
          <div
            class="panel p-4 cursor-pointer"
            style="border-radius:4px; transition: border-color 120ms;"
            (click)="open(q)"
          >
            <div class="flex items-start justify-between mb-2">
              <div class="flex items-center gap-2">
                <vq-priority [p]="q.priority" />
                <vq-mono [color]="'var(--ink)'" [weight]="600">{{ q.query_id }}</vq-mono>
                <span
                  class="chip"
                  style="color: var(--warn); border-color: var(--warn);"
                  >conf {{ q.confidence.toFixed(2) }}</span
                >
              </div>
              <vq-mono cssClass="muted" [size]="11">{{ relative(q.received_at) }}</vq-mono>
            </div>
            <div class="ink-2 truncate" style="font-size:13px; font-weight:500;">{{ q.subject }}</div>
            <div class="muted mt-1" style="font-size:11.5px;">
              {{ q.vendor_name }} · {{ q.intent }}
            </div>
            <div class="mt-3 pt-3 border-t hairline grid grid-cols-3 gap-2">
              <div>
                <div class="muted uppercase" style="font-size:9.5px; letter-spacing:.04em;">Suggested intent</div>
                <span style="font-size:11.5px;">{{ q.intent }}</span>
              </div>
              <div>
                <div class="muted uppercase" style="font-size:9.5px; letter-spacing:.04em;">KB cosine</div>
                <vq-mono [size]="14" [weight]="600">{{ q.kb_match.toFixed(2) }}</vq-mono>
              </div>
              <div>
                <div class="muted uppercase" style="font-size:9.5px; letter-spacing:.04em;">Best path</div>
                <vq-path-badge [letter]="q.kb_match > 0.6 ? 'A' : 'B'" size="sm" />
              </div>
            </div>
            <div class="flex items-center gap-2 mt-3" (click)="$event.stopPropagation()">
              <button class="btn btn-accent"><vq-icon name="check" [size]="12" /> Approve</button>
              <button class="btn"><vq-icon name="pencil" [size]="12" /> Correct</button>
              <button class="btn"><vq-icon name="route" [size]="12" /> Force Path B</button>
            </div>
          </div>
        }
      </div>
    </div>
  `,
})
export class TriagePage {
  readonly #drawer = inject(DrawerService);
  readonly #queries = inject(QueriesStore);
  protected readonly role = inject(RoleService);

  protected readonly endpointsOpen = signal(false);
  protected readonly endpoints = ENDPOINTS_TRIAGE;

  protected readonly queue = computed(() =>
    this.#queries.list().filter((q) => q.processing_path === 'C').slice(0, 8),
  );

  protected open(q: Query): void {
    this.#drawer.showQuery(q);
  }

  protected relative(iso: string): string {
    return relativeTime(iso);
  }
}
