import { Injectable, computed, signal } from '@angular/core';
import type { Priority, Query, QueryMessage, QueryStatus } from '../shared/models/query';
import { SEED_QUERIES } from './queries.seed';

export interface QueryStats {
  readonly total: number;
  readonly open: number;
  readonly inProgress: number;
  readonly awaiting: number;
  readonly resolved: number;
  readonly breached: number;
}

@Injectable({ providedIn: 'root' })
export class QueriesStore {
  readonly #queries = signal<readonly Query[]>(SEED_QUERIES);
  readonly #statusFilter = signal<QueryStatus | ''>('');
  readonly #priorityFilter = signal<Priority | ''>('');

  readonly queries = this.#queries.asReadonly();
  readonly statusFilter = this.#statusFilter.asReadonly();
  readonly priorityFilter = this.#priorityFilter.asReadonly();

  readonly filtered = computed<readonly Query[]>(() => {
    const s = this.#statusFilter();
    const p = this.#priorityFilter();
    return this.#queries().filter(
      (q) => (s === '' || q.status === s) && (p === '' || q.pri === p),
    );
  });

  readonly recent = computed<readonly Query[]>(() => this.#queries().slice(0, 4));

  readonly stats = computed<QueryStats>(() => {
    const all = this.#queries();
    return {
      total: all.length,
      open: all.filter((q) => q.status === 'Open').length,
      inProgress: all.filter((q) => q.status === 'In Progress').length,
      awaiting: all.filter((q) => q.status === 'Awaiting Vendor').length,
      resolved: all.filter((q) => q.status === 'Resolved').length,
      breached: all.filter((q) => q.slaCls === 'sla-brch').length,
    };
  });

  readonly activeCount = computed<number>(() => {
    const s = this.stats();
    return s.open + s.inProgress + s.awaiting;
  });

  findById(id: string): Query | undefined {
    return this.#queries().find((q) => q.id === id);
  }

  setStatusFilter(v: QueryStatus | ''): void {
    this.#statusFilter.set(v);
  }

  setPriorityFilter(v: Priority | ''): void {
    this.#priorityFilter.set(v);
  }

  clearFilters(): void {
    this.#statusFilter.set('');
    this.#priorityFilter.set('');
  }

  add(q: Query): void {
    this.#queries.update((xs) => [q, ...xs]);
  }

  appendMessage(id: string, msg: QueryMessage): void {
    this.#queries.update((xs) =>
      xs.map((q) => (q.id === id ? { ...q, msgs: [...q.msgs, msg] } : q)),
    );
  }
}
