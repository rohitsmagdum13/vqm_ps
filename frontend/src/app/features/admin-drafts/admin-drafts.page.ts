import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { DatePipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { DraftApprovalsStore } from '../../data/draft-approvals.store';
import type { DraftApprovalListItem } from '../../shared/models/draft-approval';

function confidenceClass(c: number | null): string {
  if (c === null) return 'bg-surface-2 text-fg-dim border border-border-light';
  if (c < 0.6) return 'bg-error/15 text-error border border-error/30';
  if (c < 0.75) return 'bg-warn/15 text-warn border border-warn/30';
  return 'bg-success/15 text-success border border-success/30';
}

@Component({
  selector: 'app-admin-drafts-page',
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
          >✉️</div>
          <div class="min-w-0">
            <h1 class="text-xl font-semibold text-fg tracking-tight">Draft Approvals</h1>
            <p class="mt-1 text-xs text-fg-dim">
              AI-drafted Path A responses waiting for human review. Approve, edit, or reject before the email reaches the vendor.
            </p>
          </div>
        </div>
        <div class="flex items-center gap-3 text-xs text-fg-dim">
          <span class="inline-flex items-center gap-1.5">
            <span class="inline-block h-2 w-2 rounded-full bg-warn"></span>
            {{ count() }} pending
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
          Failed to load drafts: {{ err }}
          <button type="button" (click)="refresh()" class="ml-2 underline hover:no-underline">Retry</button>
        </div>
      }

      @if (rows().length === 0) {
        <div
          class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-10 text-center text-sm text-fg-dim"
        >
          @if (loading() && !loaded()) {
            Loading drafts…
          } @else {
            No drafts waiting for approval.
          }
        </div>
      } @else {
        <div class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm overflow-hidden">
          <div class="overflow-x-auto">
            <table class="w-full border-collapse text-sm">
              <thead class="bg-surface-2 text-fg-dim">
                <tr>
                  <th class="px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">Query ID</th>
                  <th class="px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">Subject</th>
                  <th class="px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">Vendor</th>
                  <th class="hidden md:table-cell px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">Intent</th>
                  <th class="px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">Confidence</th>
                  <th class="hidden lg:table-cell px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">Ticket</th>
                  <th class="px-4 py-2 text-right text-[10px] font-mono tracking-wider uppercase">Actions</th>
                </tr>
              </thead>
              <tbody>
                @for (d of rows(); track d.query_id) {
                  <tr class="border-t border-border-light hover:bg-surface-2 transition">
                    <td class="px-4 py-3 font-mono text-xs text-fg">{{ d.query_id }}</td>
                    <td class="px-4 py-3 text-fg max-w-[300px]">
                      <div class="truncate" [title]="d.subject || ''">{{ d.subject || '(no subject)' }}</div>
                      <div class="text-[10px] text-fg-dim mt-0.5">drafted {{ d.drafted_at | date: 'MMM d, h:mm a' }}</div>
                    </td>
                    <td class="px-4 py-3 text-fg-dim text-xs font-mono">{{ d.vendor_id || '—' }}</td>
                    <td class="hidden md:table-cell px-4 py-3 text-fg-dim text-xs whitespace-nowrap">{{ d.intent || '—' }}</td>
                    <td class="px-4 py-3 text-xs">
                      <span
                        class="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-mono"
                        [class]="confidenceClass(d.confidence)"
                      >{{ d.confidence === null ? '—' : d.confidence.toFixed(2) }}</span>
                    </td>
                    <td class="hidden lg:table-cell px-4 py-3 font-mono text-[11px] text-fg-dim">{{ d.ticket_id || '—' }}</td>
                    <td class="px-4 py-3 text-right whitespace-nowrap">
                      <a
                        [routerLink]="['/admin/draft-approvals', d.query_id]"
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
export class AdminDraftsPage {
  readonly #store = inject(DraftApprovalsStore);

  protected readonly rows = computed<readonly DraftApprovalListItem[]>(() => this.#store.items());
  protected readonly count = this.#store.count;
  protected readonly loading = this.#store.loading;
  protected readonly loaded = this.#store.loaded;
  protected readonly error = this.#store.error;

  protected readonly confidenceClass = confidenceClass;

  constructor() {
    if (!this.#store.loaded()) {
      void this.#store.refresh();
    }
  }

  protected refresh(): void {
    void this.#store.refresh();
  }
}
