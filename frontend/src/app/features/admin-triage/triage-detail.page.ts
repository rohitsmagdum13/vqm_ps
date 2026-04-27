import { ChangeDetectionStrategy, Component, computed, effect, inject, signal } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { TriageStore } from '../../data/triage.store';
import { ConfidenceCard } from './confidence-card';
import { CopilotPanel } from './copilot-panel';
import { CorrectionForm } from './correction-form';

@Component({
  selector: 'app-triage-detail-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, DatePipe, DecimalPipe, ConfidenceCard, CopilotPanel, CorrectionForm],
  template: `
    <section class="space-y-6 animate-[fade-up_0.3s_ease-out]">
      @if (case(); as c) {
        <header
          class="flex items-start justify-between gap-3 flex-wrap rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-5"
        >
          <div class="flex items-start gap-3 min-w-0 flex-1">
            <a
              routerLink="/admin/triage"
              class="text-fg-dim hover:text-fg text-sm mt-1"
              aria-label="Back to triage queue"
            >←</a>
            <div class="min-w-0">
              <div class="flex items-center gap-2 flex-wrap">
                <h1 class="text-xl font-semibold text-fg tracking-tight">
                  {{ c.subject }}
                </h1>
                <span
                  class="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-mono"
                  [class]="c.status === 'PENDING_REVIEW'
                    ? 'bg-error/15 text-error border border-error/30'
                    : c.status === 'IN_REVIEW'
                    ? 'bg-warn/15 text-warn border border-warn/30'
                    : 'bg-success/15 text-success border border-success/30'"
                >{{ c.status }}</span>
                @if (fetching()) {
                  <span class="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] text-fg-dim border border-border-light bg-surface-2">
                    <span class="inline-block h-1.5 w-1.5 rounded-full bg-primary animate-pulse"></span>
                    Loading details…
                  </span>
                }
              </div>
              <div class="mt-1 text-xs text-fg-dim flex items-center gap-3 flex-wrap">
                <span class="font-mono">{{ c.query_id }}</span>
                <span>·</span>
                <span>{{ c.received_at | date: 'MMM d, y, h:mm a' }}</span>
                <span>·</span>
                <span>{{ c.vendor.company_name }} ({{ c.vendor.tier }})</span>
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
                  <h2 class="text-sm font-semibold text-fg">Original query</h2>
                  <p class="mt-0.5 text-[11px] text-fg-dim">As received from vendor</p>
                </div>
                <span class="text-[10px] font-mono text-fg-dim">
                  {{ c.ai_multi_issue_detected ? 'multi-issue' : 'single-issue' }}
                </span>
              </header>
              <div class="rounded-[var(--radius-sm)] bg-surface-2 border border-border-light p-3">
                <div class="text-[11px] text-fg-dim mb-1">Subject</div>
                <div class="text-sm text-fg mb-3">{{ c.subject }}</div>
                <div class="text-[11px] text-fg-dim mb-1">Body</div>
                <p class="text-sm text-fg leading-relaxed">{{ c.body }}</p>
              </div>

              <dl class="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <dt class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">AI Intent</dt>
                  <dd class="text-fg mt-0.5">{{ c.ai_intent }}</dd>
                </div>
                <div>
                  <dt class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">Suggested Category</dt>
                  <dd class="text-fg mt-0.5">{{ c.ai_suggested_category }}</dd>
                </div>
                <div>
                  <dt class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">Urgency</dt>
                  <dd class="text-fg mt-0.5">{{ c.ai_urgency }}</dd>
                </div>
                <div>
                  <dt class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">Sentiment</dt>
                  <dd class="text-fg mt-0.5">{{ c.ai_sentiment }}</dd>
                </div>
                <div class="col-span-2">
                  <dt class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">Extracted entities</dt>
                  <dd class="text-fg mt-0.5">
                    @if (entityKeys().length === 0) {
                      <span class="text-fg-dim italic">none</span>
                    } @else {
                      <div class="flex flex-wrap gap-1.5 mt-1">
                        @for (k of entityKeys(); track k) {
                          <span class="inline-flex items-center gap-1 rounded-full bg-primary/10 text-primary border border-primary/20 px-2 py-0.5 text-[11px] font-mono">
                            {{ k }}: {{ c.ai_extracted_entities[k] }}
                          </span>
                        }
                      </div>
                    }
                  </dd>
                </div>
              </dl>
            </article>

            <app-confidence-card
              [breakdown]="c.ai_confidence_breakdown"
              [overall]="c.ai_confidence"
              [reasons]="c.ai_low_confidence_reasons"
            />

            <article
              class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-5"
            >
              <h2 class="text-sm font-semibold text-fg mb-3">Vendor profile</h2>
              <dl class="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <dt class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">Vendor ID</dt>
                  <dd class="text-fg mt-0.5 font-mono">{{ c.vendor.vendor_id }}</dd>
                </div>
                @if (c.vendor.company_name) {
                  <div>
                    <dt class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">Company</dt>
                    <dd class="text-fg mt-0.5">{{ c.vendor.company_name }}</dd>
                  </div>
                }
                @if (c.vendor.tier) {
                  <div>
                    <dt class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">Tier</dt>
                    <dd class="text-fg mt-0.5">{{ c.vendor.tier }}</dd>
                  </div>
                }
                @if (c.vendor.account_manager) {
                  <div>
                    <dt class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">Account Manager</dt>
                    <dd class="text-fg mt-0.5">{{ c.vendor.account_manager }}</dd>
                  </div>
                }
                @if (c.vendor.annual_spend_usd != null) {
                  <div>
                    <dt class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">Annual Spend</dt>
                    <dd class="text-fg mt-0.5">$ {{ c.vendor.annual_spend_usd | number }}</dd>
                  </div>
                }
                @if (c.vendor.primary_contact) {
                  <div class="col-span-2">
                    <dt class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">Primary Contact</dt>
                    <dd class="text-fg mt-0.5 font-mono">{{ c.vendor.primary_contact }}</dd>
                  </div>
                }
                @if (!c.vendor.company_name && !c.vendor.tier) {
                  <div class="col-span-2 text-fg-dim text-[11px]">
                    Rich vendor profile not loaded — wire <span class="font-mono">/vendors/{{ c.vendor.vendor_id }}</span> to populate.
                  </div>
                }
              </dl>
            </article>
          </div>

          <div class="space-y-6">
            <app-copilot-panel [queryId]="c.query_id" />
            <app-correction-form [case]="c" />
          </div>
        </div>
      } @else {
        <div
          class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-10 text-center"
        >
          <p class="text-sm text-fg-dim">Triage case not found.</p>
          <a
            routerLink="/admin/triage"
            class="inline-block mt-3 text-xs font-semibold text-primary hover:underline"
          >← Back to queue</a>
        </div>
      }
    </section>
  `,
})
export class TriageDetailPage {
  readonly #store = inject(TriageStore);
  readonly #route = inject(ActivatedRoute);

  readonly #queryId = toSignal(this.#route.paramMap, {
    initialValue: this.#route.snapshot.paramMap,
  });

  protected readonly case = computed(() => {
    const id = this.#queryId().get('id');
    return id ? this.#store.byId(id) : undefined;
  });

  protected readonly entityKeys = computed<readonly string[]>(() => {
    const c = this.case();
    return c ? Object.keys(c.ai_extracted_entities) : [];
  });

  /** True until the detail fetch (loadPackage) returns for this id. */
  protected readonly fetching = signal<boolean>(false);

  // Track which query_ids we've already loaded so we don't refetch on
  // every change-detection pass.
  readonly #loadedIds = new Set<string>();

  constructor() {
    // Whenever the routed query_id changes and we haven't fetched the
    // full package for it yet, hit /triage/{id} so subject / body /
    // confidence_breakdown / extracted_entities populate the store.
    // After the package returns, fire a follow-up /vendors/{vendor_id}
    // fetch to fill in the rich Salesforce profile (tier, category,
    // SLA, etc.) — kept as a separate call so a slow Salesforce hop
    // doesn't block the main detail render.
    effect(() => {
      const id = this.#queryId().get('id');
      if (!id || this.#loadedIds.has(id)) return;
      this.#loadedIds.add(id);
      this.fetching.set(true);
      void (async () => {
        const detailed = await this.#store.loadPackage(id);
        this.fetching.set(false);
        const vendorId = detailed?.vendor.vendor_id;
        if (vendorId && vendorId !== '—') {
          void this.#store.loadVendorProfile(id, vendorId);
        }
      })();
    });

    // Mark case as IN_REVIEW once the reviewer opens it (mirrors the
    // backend status update we'll do when POST /triage/{id}/review fires).
    effect(() => {
      const c = this.case();
      if (c && c.status === 'PENDING_REVIEW') {
        this.#store.setStatus(c.query_id, 'IN_REVIEW');
      }
    });
  }
}
