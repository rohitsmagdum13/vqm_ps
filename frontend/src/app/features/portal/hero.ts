import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

@Component({
  selector: 'app-portal-hero',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section
      class="relative overflow-hidden rounded-[var(--radius-lg)] bg-gradient-to-br from-primary via-secondary to-secondary text-surface px-6 py-6 shadow-md flex items-center gap-5"
    >
      <div
        class="h-14 w-14 shrink-0 rounded-[var(--radius-md)] bg-surface/10 border border-surface/20 grid place-items-center"
        aria-hidden="true"
      >
        <svg viewBox="0 0 26 26" class="h-7 w-7" fill="none">
          <rect x="3" y="7" width="20" height="13" rx="2.5" stroke="currentColor" stroke-width="1.8" />
          <path d="M8 13h10M8 16.5h6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
        </svg>
      </div>
      <div class="flex-1 min-w-0">
        <div class="text-xl font-semibold tracking-tight truncate">
          Welcome back, {{ firstName() }}
        </div>
        <div class="text-sm text-surface/80 mt-0.5 truncate">
          {{ company() }} · Queries processed by AI in real-time.
        </div>
      </div>
      <div class="flex items-center gap-2 shrink-0">
        <button
          type="button"
          (click)="newQuery.emit()"
          class="inline-flex items-center gap-2 rounded-[var(--radius-sm)] bg-accent text-secondary font-medium text-xs px-3 py-1.5 hover:brightness-95 transition"
        >
          <span aria-hidden="true">＋</span> New Query
        </button>
        <button
          type="button"
          (click)="viewAll.emit()"
          class="inline-flex items-center gap-1 rounded-[var(--radius-sm)] bg-surface/10 text-surface border border-surface/20 text-xs px-3 py-1.5 hover:bg-surface/20 transition"
        >View All →</button>
      </div>
    </section>
  `,
})
export class PortalHero {
  readonly firstName = input.required<string>();
  readonly company = input.required<string>();

  readonly newQuery = output<void>();
  readonly viewAll = output<void>();
}
