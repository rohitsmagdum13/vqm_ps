import { ChangeDetectionStrategy, Component, computed, effect, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { AuthService } from '../../core/auth/auth.service';
import { QueriesStore } from '../../data/queries.store';
import type { Priority, QueryStatus } from '../../shared/models/query';
import { SpinnerComponent } from '../../shared/ui/spinner/spinner';
import { QueryFilters } from './query-filters';
import { QueryStatsComponent } from './query-stats';
import { QueryTable } from './query-table';

@Component({
  selector: 'app-queries-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [SpinnerComponent, QueryFilters, QueryStatsComponent, QueryTable],
  template: `
    <section class="space-y-8 animate-[fade-up_0.3s_ease-out]">
      <header
        class="flex items-start justify-between gap-4 flex-wrap rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-5"
      >
        <div class="flex items-start gap-3">
          <div
            class="h-10 w-10 shrink-0 rounded-full bg-primary/10 text-primary flex items-center justify-center text-lg"
            aria-hidden="true"
          >
            📋
          </div>
          <div>
            <h1 class="text-xl font-semibold text-fg tracking-tight">Queries</h1>
            <p class="mt-1 text-xs text-fg-dim">
              Showing {{ store.filtered().length }} of {{ store.queries().length }} · filter, review, and respond.
            </p>
          </div>
        </div>
        <div class="flex items-center gap-2">
          @if (store.loading() && store.hasLoaded()) {
            <ui-spinner size="sm" label="Refreshing" />
          }
          <button
            type="button"
            (click)="refresh()"
            [disabled]="store.loading()"
            class="inline-flex items-center gap-2 rounded-[var(--radius-sm)] border border-border-light text-fg text-xs font-semibold px-3 py-2 hover:bg-surface-2 disabled:opacity-50 transition"
          >↻ Refresh</button>
        </div>
      </header>

      @if (store.error(); as err) {
        <div
          role="alert"
          class="rounded-[var(--radius-md)] border border-error/30 bg-error/10 text-error text-xs px-4 py-3"
        >
          Failed to load queries: {{ err }}
          <button
            type="button"
            (click)="refresh()"
            class="ml-2 underline hover:no-underline"
          >Retry</button>
        </div>
      }

      <app-query-filters
        [(status)]="statusFilter"
        [(priority)]="priorityFilter"
        [canCreate]="canCreate()"
        (newQuery)="goWizard()"
      />

      <app-query-stats [stats]="store.stats()" />

      @if (!store.hasLoaded() && store.loading()) {
        <div class="py-16 flex justify-center">
          <ui-spinner size="lg" label="Loading queries" />
        </div>
      } @else {
        <app-query-table
          [rows]="store.filtered()"
          [showVendor]="isAdmin()"
          (open)="openDetail($event)"
        />
      }
    </section>
  `,
})
export class QueriesPage {
  protected readonly store = inject(QueriesStore);
  readonly #router = inject(Router);
  readonly #auth = inject(AuthService);

  protected readonly statusFilter = signal<QueryStatus | ''>(this.store.statusFilter());
  protected readonly priorityFilter = signal<Priority | ''>(this.store.priorityFilter());
  protected readonly canCreate = computed(() => this.#auth.role() === 'vendor');
  protected readonly isAdmin = computed(() => this.#auth.role() === 'admin');

  constructor() {
    effect(() => this.store.setStatusFilter(this.statusFilter()));
    effect(() => this.store.setPriorityFilter(this.priorityFilter()));
    if (!this.store.hasLoaded()) {
      this.store.refresh();
    }
  }

  protected refresh(): void {
    this.store.refresh();
  }

  protected goWizard(): void {
    void this.#router.navigate(this.#auth.vendorPath('wizard'));
  }

  protected openDetail(id: string): void {
    if (this.#auth.role() === 'admin') {
      void this.#router.navigate(['/admin/queries', id]);
      return;
    }
    void this.#router.navigate(this.#auth.vendorPath('queries', id));
  }
}
