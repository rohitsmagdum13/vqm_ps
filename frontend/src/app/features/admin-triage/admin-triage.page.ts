import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { TriageStore } from '../../data/triage.store';
import type { TriageCase, TriageStatus } from '../../shared/models/triage';

type Tab = 'PENDING_REVIEW' | 'IN_REVIEW' | 'COMPLETED';

function confidenceClass(c: number): string {
  if (c < 0.6) return 'bg-error/15 text-error border border-error/30';
  if (c < 0.75) return 'bg-warn/15 text-warn border border-warn/30';
  return 'bg-success/15 text-success border border-success/30';
}

function urgencyClass(u: TriageCase['ai_urgency']): string {
  switch (u) {
    case 'CRITICAL':
      return 'bg-error/15 text-error border border-error/30';
    case 'HIGH':
      return 'bg-warn/15 text-warn border border-warn/30';
    case 'MEDIUM':
      return 'bg-primary/10 text-primary border border-primary/20';
    default:
      return 'bg-surface-2 text-fg-dim border border-border-light';
  }
}

function tierClass(t: TriageCase['vendor']['tier']): string {
  switch (t) {
    case 'Platinum':
      return 'bg-slate-500/15 text-slate-700 border border-slate-500/40';
    case 'Gold':
      return 'bg-yellow-500/15 text-yellow-700 border border-yellow-500/40';
    case 'Silver':
      return 'bg-zinc-400/20 text-zinc-700 border border-zinc-500/40';
    case 'Bronze':
      return 'bg-amber-700/15 text-amber-800 border border-amber-700/40';
    default:
      return 'bg-surface-2 text-fg-dim border border-border-light';
  }
}

@Component({
  selector: 'app-admin-triage-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, DatePipe],
  template: `
    <section class="space-y-6 animate-[fade-up_0.3s_ease-out]">
      <header
        class="flex items-start justify-between gap-3 flex-wrap rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-5"
      >
        <div class="flex items-start gap-3 min-w-0 flex-1">
          <div
            class="h-10 w-10 shrink-0 rounded-full bg-primary/10 text-primary flex items-center justify-center text-lg"
          >🧠</div>
          <div class="min-w-0">
            <h1 class="text-xl font-semibold text-fg tracking-tight">Path C — Triage Review</h1>
            <p class="mt-1 text-xs text-fg-dim">
              Low-confidence queries paused for human review. Use the AI Copilot to investigate before submitting corrections.
            </p>
          </div>
        </div>
        <div class="flex items-center gap-3 text-xs text-fg-dim">
          <span class="inline-flex items-center gap-1.5">
            <span class="inline-block h-2 w-2 rounded-full bg-error"></span>
            {{ pendingCount() }} pending
          </span>
          <span class="inline-flex items-center gap-1.5">
            <span class="inline-block h-2 w-2 rounded-full bg-warn"></span>
            {{ inReviewCount() }} in review
          </span>
          <span class="inline-flex items-center gap-1.5">
            <span class="inline-block h-2 w-2 rounded-full bg-success"></span>
            {{ completedCount() }} completed
          </span>
          <button
            type="button"
            (click)="refresh()"
            [disabled]="loading()"
            class="ml-2 text-[11px] text-primary hover:underline disabled:opacity-50"
          >{{ loading() ? 'Refreshing…' : 'Refresh' }}</button>
        </div>
      </header>

      @if (error(); as err) {
        <div role="alert" class="rounded-[var(--radius-md)] border border-error/30 bg-error/10 text-error text-xs px-4 py-3">
          Failed to load triage queue: {{ err }}
          <button type="button" (click)="refresh()" class="ml-2 underline hover:no-underline">Retry</button>
        </div>
      }

      <div role="tablist" class="inline-flex gap-1 bg-surface border border-border-light rounded-[var(--radius-sm)] p-1">
        @for (t of tabs; track t.id) {
          <button
            type="button"
            role="tab"
            (click)="tab.set(t.id)"
            [attr.aria-selected]="tab() === t.id"
            [class]="tab() === t.id
              ? 'px-3 py-1.5 text-xs font-semibold rounded-[var(--radius-sm)] bg-primary text-surface'
              : 'px-3 py-1.5 text-xs font-medium rounded-[var(--radius-sm)] text-fg-dim hover:text-fg'"
          >{{ t.label }}</button>
        }
      </div>

      @if (rows().length === 0) {
        <div
          class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-10 text-center text-sm text-fg-dim"
        >
          @if (loading() && !loaded()) {
            Loading triage queue…
          } @else {
            No cases in this state.
          }
        </div>
      } @else {
        <div class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm overflow-hidden">
          <div class="overflow-x-auto">
            <table class="w-full border-collapse text-sm min-w-[1100px]">
              <thead class="bg-surface-2 text-fg-dim">
                <tr>
                  <th class="px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">Query ID</th>
                  <th class="px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">Subject</th>
                  <th class="px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">Vendor</th>
                  <th class="px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">AI Intent</th>
                  <th class="px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">Category</th>
                  <th class="px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">Confidence</th>
                  <th class="px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">Urgency</th>
                  <th class="px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">Received</th>
                  <th class="px-4 py-2 text-right text-[10px] font-mono tracking-wider uppercase">Actions</th>
                </tr>
              </thead>
              <tbody>
                @for (c of rows(); track c.query_id) {
                  <tr class="border-t border-border-light hover:bg-surface-2 transition">
                    <td class="px-4 py-3 font-mono text-xs text-fg">{{ c.query_id }}</td>
                    <td class="px-4 py-3 text-fg max-w-[260px]">
                      <div class="truncate" [title]="c.subject">{{ c.subject }}</div>
                    </td>
                    <td class="px-4 py-3 text-fg-dim text-xs">
                      <div class="flex items-center gap-2">
                        <span class="font-medium text-fg truncate max-w-[140px]" [title]="c.vendor.company_name || c.vendor.vendor_id">
                          {{ c.vendor.company_name || c.vendor.vendor_id }}
                        </span>
                        @if (c.vendor.tier) {
                          <span
                            class="inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-semibold"
                            [class]="tierClass(c.vendor.tier)"
                          >{{ c.vendor.tier }}</span>
                        }
                      </div>
                    </td>
                    <td class="px-4 py-3 text-fg-dim text-xs whitespace-nowrap">{{ c.ai_intent }}</td>
                    <td class="px-4 py-3 text-fg-dim text-xs whitespace-nowrap">{{ c.ai_suggested_category }}</td>
                    <td class="px-4 py-3 text-xs">
                      <span
                        class="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-mono"
                        [class]="confidenceClass(c.ai_confidence)"
                      >{{ c.ai_confidence.toFixed(2) }}</span>
                    </td>
                    <td class="px-4 py-3 text-xs">
                      <span
                        class="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold"
                        [class]="urgencyClass(c.ai_urgency)"
                      >{{ c.ai_urgency }}</span>
                    </td>
                    <td class="px-4 py-3 text-fg-dim text-xs whitespace-nowrap">
                      {{ c.received_at | date: 'MMM d, h:mm a' }}
                    </td>
                    <td class="px-4 py-3 text-right whitespace-nowrap">
                      <a
                        [routerLink]="['/admin/triage', c.query_id]"
                        class="text-xs font-semibold text-primary hover:underline"
                      >Review →</a>
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        </div>
      }
    </section>
  `,
})
export class AdminTriagePage {
  readonly #store = inject(TriageStore);

  protected readonly tabs: ReadonlyArray<{ id: Tab; label: string }> = [
    { id: 'PENDING_REVIEW', label: 'Pending' },
    { id: 'IN_REVIEW', label: 'In Review' },
    { id: 'COMPLETED', label: 'Completed' },
  ];

  protected readonly tab = signal<Tab>('PENDING_REVIEW');

  protected readonly rows = computed<readonly TriageCase[]>(() => {
    const t: TriageStatus = this.tab();
    return this.#store.all().filter((c) => c.status === t);
  });

  protected readonly pendingCount = computed(() => this.#store.pending().length);
  protected readonly inReviewCount = computed(() => this.#store.inReview().length);
  protected readonly completedCount = computed(() => this.#store.completed().length);
  protected readonly loading = this.#store.loading;
  protected readonly loaded = this.#store.loaded;
  protected readonly error = this.#store.error;

  protected readonly confidenceClass = confidenceClass;
  protected readonly urgencyClass = urgencyClass;
  protected readonly tierClass = tierClass;

  constructor() {
    // Fetch the real queue from /triage/queue on first navigation.
    if (!this.#store.loaded()) {
      void this.#store.refresh();
    }
  }

  protected refresh(): void {
    void this.#store.refresh();
  }
}
