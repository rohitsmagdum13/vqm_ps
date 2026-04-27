import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { PathBStore } from '../../data/path-b.store';
import type {
  InvestigationTeam,
  PathBTicket,
  TicketPriority,
  TicketStatus,
} from '../../shared/models/path-b';
import { SlaProgress } from './sla-progress';

type Tab = 'OPEN' | 'IN_PROGRESS' | 'RESOLVED';

const TEAM_OPTIONS: ReadonlyArray<InvestigationTeam | 'ALL'> = [
  'ALL',
  'AP-FINANCE',
  'PROCUREMENT',
  'LOGISTICS',
  'COMPLIANCE',
  'TECH-SUPPORT',
];

function priorityClass(p: TicketPriority): string {
  switch (p) {
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

function statusClass(s: TicketStatus): string {
  switch (s) {
    case 'OPEN':
      return 'bg-error/15 text-error border border-error/30';
    case 'IN_PROGRESS':
      return 'bg-primary/10 text-primary border border-primary/20';
    case 'PENDING_VENDOR':
      return 'bg-warn/15 text-warn border border-warn/30';
    case 'RESOLVED':
      return 'bg-success/15 text-success border border-success/30';
  }
}

@Component({
  selector: 'app-admin-path-b-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, DatePipe, SlaProgress],
  template: `
    <section class="space-y-6 animate-[fade-up_0.3s_ease-out]">
      <header
        class="flex items-start justify-between gap-3 flex-wrap rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-5"
      >
        <div class="flex items-start gap-3 min-w-0 flex-1">
          <div
            class="h-10 w-10 shrink-0 rounded-full bg-primary/10 text-primary flex items-center justify-center text-lg"
          >🔍</div>
          <div class="min-w-0">
            <h1 class="text-xl font-semibold text-fg tracking-tight">Path B — Team Investigations</h1>
            <p class="mt-1 text-xs text-fg-dim">
              Tickets where the team must investigate before AI can draft a resolution. SLA clock is running.
            </p>
          </div>
        </div>
        <div class="flex items-center gap-3 text-xs text-fg-dim">
          <span class="inline-flex items-center gap-1.5">
            <span class="inline-block h-2 w-2 rounded-full bg-error"></span>
            {{ openCount() }} open
          </span>
          <span class="inline-flex items-center gap-1.5">
            <span class="inline-block h-2 w-2 rounded-full bg-primary"></span>
            {{ inProgressCount() }} in progress
          </span>
          <span class="inline-flex items-center gap-1.5">
            <span class="inline-block h-2 w-2 rounded-full bg-success"></span>
            {{ resolvedCount() }} resolved
          </span>
        </div>
      </header>

      <div class="flex flex-wrap items-center gap-3">
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

        <div class="ml-auto flex items-center gap-2">
          <span class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">Team</span>
          <select
            [value]="teamFilter()"
            (change)="onTeamChange($event)"
            class="text-xs bg-surface border border-border-light rounded-[var(--radius-sm)] px-2 py-1.5 outline-none focus:border-primary/40"
          >
            @for (team of teamOptions; track team) {
              <option [value]="team">{{ team === 'ALL' ? 'All teams' : team }}</option>
            }
          </select>
        </div>
      </div>

      @if (rows().length === 0) {
        <div
          class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-10 text-center text-sm text-fg-dim"
        >No tickets in this state.</div>
      } @else {
        <div class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm overflow-hidden">
          <div class="overflow-x-auto">
            <table class="w-full border-collapse text-sm">
              <thead class="bg-surface-2 text-fg-dim">
                <tr>
                  <th class="px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">Ticket</th>
                  <th class="px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">Subject</th>
                  <th class="hidden md:table-cell px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">Vendor</th>
                  <th class="px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">Team</th>
                  <th class="px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">Priority</th>
                  <th class="hidden lg:table-cell px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase w-[200px]">SLA</th>
                  <th class="px-4 py-2 text-right text-[10px] font-mono tracking-wider uppercase">Actions</th>
                </tr>
              </thead>
              <tbody>
                @for (t of rows(); track t.ticket_id) {
                  <tr class="border-t border-border-light hover:bg-surface-2 transition">
                    <td class="px-4 py-3 text-xs">
                      <div class="font-mono text-fg">{{ t.ticket_id }}</div>
                      <div class="font-mono text-[10px] text-fg-dim">{{ t.query_id }}</div>
                    </td>
                    <td class="px-4 py-3 text-fg max-w-[280px]">
                      <div class="truncate" [title]="t.subject">{{ t.subject }}</div>
                      <div class="text-[10px] text-fg-dim mt-0.5">
                        <span
                          class="inline-flex items-center rounded-full px-1.5 py-0.5 font-semibold mr-1"
                          [class]="statusClass(t.status)"
                        >{{ t.status }}</span>
                        opened {{ t.opened_at | date: 'MMM d, h:mm a' }}
                      </div>
                    </td>
                    <td class="hidden md:table-cell px-4 py-3 text-xs text-fg-dim max-w-[150px]">
                      <div class="truncate text-fg" [title]="t.vendor.company_name">{{ t.vendor.company_name }}</div>
                      <div class="text-[10px]">{{ t.vendor.tier }}</div>
                    </td>
                    <td class="px-4 py-3 text-xs font-mono text-fg whitespace-nowrap">{{ t.team }}</td>
                    <td class="px-4 py-3 text-xs">
                      <span
                        class="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold"
                        [class]="priorityClass(t.priority)"
                      >{{ t.priority }}</span>
                    </td>
                    <td class="hidden lg:table-cell px-4 py-3 w-[200px]">
                      <app-sla-progress
                        [elapsedHours]="t.sla_elapsed_hours"
                        [targetHours]="t.sla_target_hours"
                      />
                    </td>
                    <td class="px-4 py-3 text-right whitespace-nowrap">
                      <a
                        [routerLink]="['/admin/path-b', t.ticket_id]"
                        class="text-xs font-semibold text-primary hover:underline"
                      >Investigate →</a>
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
export class AdminPathBPage {
  readonly #store = inject(PathBStore);

  protected readonly tabs: ReadonlyArray<{ id: Tab; label: string }> = [
    { id: 'OPEN', label: 'Open' },
    { id: 'IN_PROGRESS', label: 'In Progress' },
    { id: 'RESOLVED', label: 'Resolved' },
  ];

  protected readonly tab = signal<Tab>('OPEN');
  protected readonly teamOptions = TEAM_OPTIONS;

  protected readonly rows = computed<readonly PathBTicket[]>(() => {
    const t = this.tab();
    if (t === 'OPEN') return this.#store.open();
    if (t === 'IN_PROGRESS') return this.#store.inProgress();
    return this.#store.resolved();
  });

  protected readonly teamFilter = this.#store.teamFilter;
  protected readonly openCount = this.#store.openCount;
  protected readonly inProgressCount = this.#store.inProgressCount;
  protected readonly resolvedCount = this.#store.resolvedCount;

  protected readonly priorityClass = priorityClass;
  protected readonly statusClass = statusClass;

  protected onTeamChange(event: Event): void {
    const value = (event.target as HTMLSelectElement).value as InvestigationTeam | 'ALL';
    this.#store.setTeamFilter(value);
  }
}
