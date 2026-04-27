import { Injectable, computed, signal } from '@angular/core';
import type {
  InvestigationTeam,
  PathBTicket,
  ResolutionSubmission,
  TicketStatus,
} from '../shared/models/path-b';
import { SEED_PATH_B_TICKETS } from './path-b.seed';

@Injectable({ providedIn: 'root' })
export class PathBStore {
  readonly #tickets = signal<readonly PathBTicket[]>(SEED_PATH_B_TICKETS);
  readonly #resolutions = signal<readonly ResolutionSubmission[]>([]);
  readonly #teamFilter = signal<InvestigationTeam | 'ALL'>('ALL');

  readonly all = computed<readonly PathBTicket[]>(() => this.#tickets());
  readonly teamFilter = this.#teamFilter.asReadonly();

  readonly open = computed<readonly PathBTicket[]>(() =>
    this.#filterByTeam(this.#tickets().filter((t) => t.status === 'OPEN')),
  );
  readonly inProgress = computed<readonly PathBTicket[]>(() =>
    this.#filterByTeam(
      this.#tickets().filter((t) => t.status === 'IN_PROGRESS' || t.status === 'PENDING_VENDOR'),
    ),
  );
  readonly resolved = computed<readonly PathBTicket[]>(() =>
    this.#filterByTeam(this.#tickets().filter((t) => t.status === 'RESOLVED')),
  );

  readonly openCount = computed(() => this.#tickets().filter((t) => t.status === 'OPEN').length);
  readonly inProgressCount = computed(
    () =>
      this.#tickets().filter((t) => t.status === 'IN_PROGRESS' || t.status === 'PENDING_VENDOR')
        .length,
  );
  readonly resolvedCount = computed(
    () => this.#tickets().filter((t) => t.status === 'RESOLVED').length,
  );

  byId(ticketId: string): PathBTicket | undefined {
    return this.#tickets().find((t) => t.ticket_id === ticketId);
  }

  setTeamFilter(team: InvestigationTeam | 'ALL'): void {
    this.#teamFilter.set(team);
  }

  setStatus(ticketId: string, status: TicketStatus): void {
    this.#tickets.update((list) =>
      list.map((t) => (t.ticket_id === ticketId ? { ...t, status } : t)),
    );
  }

  saveNotes(ticketId: string, notes: string): void {
    this.#tickets.update((list) =>
      list.map((t) =>
        t.ticket_id === ticketId ? { ...t, resolution_notes: notes } : t,
      ),
    );
  }

  markResolved(ticketId: string, notes: string): ResolutionSubmission {
    const submission: ResolutionSubmission = {
      ticket_id: ticketId,
      resolution_notes: notes,
      resolved_at: new Date().toISOString(),
    };
    this.saveNotes(ticketId, notes);
    this.setStatus(ticketId, 'RESOLVED');
    this.#resolutions.update((list) => [...list, submission]);
    return submission;
  }

  resolutionFor(ticketId: string): ResolutionSubmission | undefined {
    return this.#resolutions().find((r) => r.ticket_id === ticketId);
  }

  #filterByTeam(list: readonly PathBTicket[]): readonly PathBTicket[] {
    const t = this.#teamFilter();
    return t === 'ALL' ? list : list.filter((x) => x.team === t);
  }
}
