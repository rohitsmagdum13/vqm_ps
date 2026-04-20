import { ChangeDetectionStrategy, Component, computed, effect, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { AuthService } from '../../core/auth/auth.service';
import { QueriesStore } from '../../data/queries.store';
import type { Priority, QueryStatus } from '../../shared/models/query';
import { QueryFilters } from './query-filters';
import { QueryStatsComponent } from './query-stats';
import { QueryTable } from './query-table';

@Component({
  selector: 'app-queries-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [QueryFilters, QueryStatsComponent, QueryTable],
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
      </header>

      <app-query-filters
        [(status)]="statusFilter"
        [(priority)]="priorityFilter"
        [canCreate]="canCreate()"
        (newQuery)="goWizard()"
      />

      <app-query-stats [stats]="store.stats()" />

      <app-query-table [rows]="store.filtered()" (open)="openDetail($event)" />
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

  constructor() {
    effect(() => this.store.setStatusFilter(this.statusFilter()));
    effect(() => this.store.setPriorityFilter(this.priorityFilter()));
  }

  protected goWizard(): void {
    void this.#router.navigate(['/wizard']);
  }

  protected openDetail(id: string): void {
    void this.#router.navigate(['/queries', id]);
  }
}
