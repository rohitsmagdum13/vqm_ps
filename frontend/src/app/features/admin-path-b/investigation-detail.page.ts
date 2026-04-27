import { ChangeDetectionStrategy, Component, computed, effect, inject, signal } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { PathBStore } from '../../data/path-b.store';
import { PathBCopilotPanel } from './path-b-copilot-panel';
import { ResolutionEditor } from './resolution-editor';
import { SlaProgress } from './sla-progress';

@Component({
  selector: 'app-investigation-detail-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    DatePipe,
    DecimalPipe,
    PathBCopilotPanel,
    ResolutionEditor,
    SlaProgress,
  ],
  template: `
    <section class="space-y-6 animate-[fade-up_0.3s_ease-out]">
      @if (ticket(); as t) {
        <header
          class="flex items-start justify-between gap-3 flex-wrap rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-5"
        >
          <div class="flex items-start gap-3 min-w-0 flex-1">
            <a
              routerLink="/admin/path-b"
              class="text-fg-dim hover:text-fg text-sm mt-1"
              aria-label="Back to investigation queue"
            >←</a>
            <div class="min-w-0">
              <div class="flex items-center gap-2 flex-wrap">
                <h1 class="text-xl font-semibold text-fg tracking-tight">{{ t.subject }}</h1>
                <span
                  class="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-mono"
                  [class]="t.status === 'RESOLVED'
                    ? 'bg-success/15 text-success border border-success/30'
                    : t.status === 'PENDING_VENDOR'
                    ? 'bg-warn/15 text-warn border border-warn/30'
                    : t.status === 'IN_PROGRESS'
                    ? 'bg-primary/10 text-primary border border-primary/20'
                    : 'bg-error/15 text-error border border-error/30'"
                >{{ t.status }}</span>
              </div>
              <div class="mt-1 text-xs text-fg-dim flex items-center gap-3 flex-wrap">
                <span class="font-mono">{{ t.ticket_id }}</span>
                <span>·</span>
                <span class="font-mono">{{ t.query_id }}</span>
                <span>·</span>
                <span>opened {{ t.opened_at | date: 'MMM d, y, h:mm a' }}</span>
                <span>·</span>
                <span>{{ t.team }}</span>
              </div>
            </div>
          </div>
        </header>

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div class="space-y-6">
            <article
              class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-5 space-y-3"
            >
              <header class="flex items-start justify-between gap-2">
                <div>
                  <h2 class="text-sm font-semibold text-fg">Vendor query</h2>
                  <p class="mt-0.5 text-[11px] text-fg-dim">Original message that triggered this ticket</p>
                </div>
                <span
                  class="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold"
                  [class]="t.priority === 'CRITICAL' ? 'bg-error/15 text-error border border-error/30'
                    : t.priority === 'HIGH' ? 'bg-warn/15 text-warn border border-warn/30'
                    : 'bg-primary/10 text-primary border border-primary/20'"
                >{{ t.priority }}</span>
              </header>

              <div class="rounded-[var(--radius-sm)] bg-surface-2 border border-border-light p-3">
                <p class="text-sm text-fg leading-relaxed">{{ t.body }}</p>
              </div>

              <dl class="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <dt class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">AI intent</dt>
                  <dd class="text-fg mt-0.5">{{ t.ai_intent }}</dd>
                </div>
                <div>
                  <dt class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">Category</dt>
                  <dd class="text-fg mt-0.5">{{ t.category }}</dd>
                </div>
                <div>
                  <dt class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">Related invoices</dt>
                  <dd class="text-fg mt-0.5 font-mono">
                    {{ t.related_invoices.length === 0 ? '—' : t.related_invoices.join(', ') }}
                  </dd>
                </div>
                <div>
                  <dt class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">Related POs</dt>
                  <dd class="text-fg mt-0.5 font-mono">
                    {{ t.related_pos.length === 0 ? '—' : t.related_pos.join(', ') }}
                  </dd>
                </div>
              </dl>
            </article>

            <article
              class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-5 space-y-3"
            >
              <header>
                <h2 class="text-sm font-semibold text-fg">SLA status</h2>
                <p class="mt-0.5 text-[11px] text-fg-dim">
                  Target {{ t.sla_target_hours }}h based on {{ t.vendor.tier }} tier and {{ t.priority }} priority
                </p>
              </header>
              <app-sla-progress
                [elapsedHours]="t.sla_elapsed_hours"
                [targetHours]="t.sla_target_hours"
              />
            </article>

            <article
              class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-5 space-y-3"
            >
              <header>
                <h2 class="text-sm font-semibold text-fg">Acknowledgment sent to vendor</h2>
                <p class="mt-0.5 text-[11px] text-fg-dim">
                  Auto-sent {{ t.acknowledgment_sent_at | date: 'MMM d, h:mm a' }} (Step 10B)
                </p>
              </header>
              <div class="rounded-[var(--radius-sm)] bg-primary/5 border border-primary/20 p-3 text-xs leading-relaxed text-fg">
                {{ t.acknowledgment_excerpt }}
              </div>
            </article>

            <article
              class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-5"
            >
              <h2 class="text-sm font-semibold text-fg mb-3">Vendor profile</h2>
              <dl class="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <dt class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">Company</dt>
                  <dd class="text-fg mt-0.5">{{ t.vendor.company_name }}</dd>
                </div>
                <div>
                  <dt class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">Tier</dt>
                  <dd class="text-fg mt-0.5">{{ t.vendor.tier }}</dd>
                </div>
                <div>
                  <dt class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">Account manager</dt>
                  <dd class="text-fg mt-0.5">{{ t.vendor.account_manager }}</dd>
                </div>
                <div>
                  <dt class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">Annual spend</dt>
                  <dd class="text-fg mt-0.5">$ {{ t.vendor.annual_spend_usd | number }}</dd>
                </div>
                <div class="col-span-2">
                  <dt class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">Primary contact</dt>
                  <dd class="text-fg mt-0.5 font-mono">{{ t.vendor.primary_contact }}</dd>
                </div>
              </dl>
            </article>
          </div>

          <div class="space-y-6">
            <app-path-b-copilot-panel
              [ticketId]="t.ticket_id"
              (draftReady)="onDraftReady($event)"
            />
            <app-resolution-editor
              [ticket]="t"
              [draftToInsert]="draftToInsert()"
            />
          </div>
        </div>
      } @else {
        <div
          class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-10 text-center"
        >
          <p class="text-sm text-fg-dim">Ticket not found.</p>
          <a
            routerLink="/admin/path-b"
            class="inline-block mt-3 text-xs font-semibold text-primary hover:underline"
          >← Back to queue</a>
        </div>
      }
    </section>
  `,
})
export class InvestigationDetailPage {
  readonly #store = inject(PathBStore);
  readonly #route = inject(ActivatedRoute);

  readonly #paramMap = toSignal(this.#route.paramMap, {
    initialValue: this.#route.snapshot.paramMap,
  });

  protected readonly ticket = computed(() => {
    const id = this.#paramMap().get('id');
    return id ? this.#store.byId(id) : undefined;
  });

  // The draft text emitted by the copilot's "Use draft →" button — passed
  // through to the resolution editor as an input.
  protected readonly draftToInsert = signal<string>('');

  constructor() {
    // Promote OPEN tickets to IN_PROGRESS the moment a team member opens them.
    effect(() => {
      const t = this.ticket();
      if (t && t.status === 'OPEN') {
        this.#store.setStatus(t.ticket_id, 'IN_PROGRESS');
      }
    });
  }

  protected onDraftReady(draft: string): void {
    this.draftToInsert.set(draft);
  }
}
