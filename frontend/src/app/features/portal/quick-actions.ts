import { ChangeDetectionStrategy, Component, output } from '@angular/core';

interface QuickAction {
  readonly id: 'new' | 'list' | 'prefs';
  readonly ico: string;
  readonly lbl: string;
  readonly sub: string;
  readonly tint: string;
}

const ACTIONS: readonly QuickAction[] = [
  { id: 'new', ico: '📝', lbl: 'New Query', sub: 'Raise a new ticket', tint: 'bg-primary/10' },
  { id: 'list', ico: '📋', lbl: 'My Queries', sub: 'Track submissions', tint: 'bg-success/10' },
  { id: 'prefs', ico: '⚙️', lbl: 'Preferences', sub: 'Notifications & profile', tint: 'bg-warn/10' },
];

@Component({
  selector: 'app-portal-quick-actions',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="grid grid-cols-1 sm:grid-cols-3 gap-8">
      @for (a of actions; track a.id) {
        <button
          type="button"
          (click)="pick(a.id)"
          class="group flex items-center gap-3 text-left rounded-[var(--radius-md)] bg-surface border border-border-light px-4 py-3 shadow-sm hover:border-primary hover:shadow-md transition"
        >
          <span
            class="h-10 w-10 rounded-[var(--radius-sm)] grid place-items-center text-lg"
            [class]="a.tint"
            aria-hidden="true"
          >{{ a.ico }}</span>
          <span class="flex-1 min-w-0">
            <span class="block text-sm font-semibold text-fg">{{ a.lbl }}</span>
            <span class="block text-xs text-fg-dim">{{ a.sub }}</span>
          </span>
          <span class="text-fg-dim group-hover:text-primary transition" aria-hidden="true">→</span>
        </button>
      }
    </div>
  `,
})
export class PortalQuickActions {
  readonly newQuery = output<void>();
  readonly viewQueries = output<void>();
  readonly openPrefs = output<void>();

  protected readonly actions = ACTIONS;

  protected pick(id: QuickAction['id']): void {
    if (id === 'new') this.newQuery.emit();
    else if (id === 'list') this.viewQueries.emit();
    else this.openPrefs.emit();
  }
}
