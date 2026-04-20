import { ChangeDetectionStrategy, Component, model } from '@angular/core';
import { PREF_NAV, type PrefSection } from './preferences.data';

@Component({
  selector: 'app-pref-nav',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <nav
      class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-3 flex flex-col gap-1"
      aria-label="Preference sections"
    >
      <div
        class="text-[10px] font-mono uppercase tracking-wider text-fg-dim px-2 pt-1 pb-1.5"
      >
        Preferences
      </div>
      @for (item of items; track item.id) {
        <button
          type="button"
          (click)="active.set(item.id)"
          [attr.aria-current]="active() === item.id ? 'page' : null"
          class="flex items-center gap-2 rounded-[var(--radius-sm)] px-2.5 py-2 text-sm text-left transition"
          [class]="rowClass(item.id)"
        >
          <span class="text-base leading-5 shrink-0" aria-hidden="true">{{ item.ico }}</span>
          <span>{{ item.label }}</span>
        </button>
      }
    </nav>
  `,
})
export class PrefNav {
  readonly active = model.required<PrefSection>();
  protected readonly items = PREF_NAV;

  protected rowClass(id: PrefSection): string {
    return this.active() === id
      ? 'bg-primary/10 text-primary font-semibold'
      : 'text-fg hover:bg-surface-2';
  }
}
