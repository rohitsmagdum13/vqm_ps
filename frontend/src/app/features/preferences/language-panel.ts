import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { PreferencesStore } from '../../data/preferences.store';
import { LANGUAGES } from './preferences.data';

@Component({
  selector: 'app-language-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="rounded-[var(--radius-sm)] border border-border-light bg-surface px-4 py-3">
      <div class="text-sm font-medium text-fg">Interface language</div>
      <div class="mt-0.5 text-[11px] text-fg-dim">
        Choose how the VQMS portal speaks to you. Emails still use the sender's language.
      </div>
      <div class="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-2">
        @for (lang of options; track lang.code) {
          <button
            type="button"
            (click)="select(lang.code)"
            [attr.aria-pressed]="isActive(lang.code)"
            class="flex items-center gap-2 rounded-[var(--radius-sm)] border px-3 py-2 text-sm transition text-left"
            [class]="rowClass(lang.code)"
          >
            <span
              class="h-2.5 w-2.5 rounded-full border shrink-0"
              [class]="dotClass(lang.code)"
              aria-hidden="true"
            ></span>
            <span class="truncate">{{ lang.label }}</span>
            <span class="ml-auto text-[10px] font-mono text-fg-dim uppercase">{{ lang.code }}</span>
          </button>
        }
      </div>
    </div>
  `,
})
export class LanguagePanel {
  readonly #store = inject(PreferencesStore);
  protected readonly options = LANGUAGES;

  protected isActive(code: string): boolean {
    return this.#store.lang() === code;
  }

  protected select(code: string): void {
    this.#store.setLang(code);
  }

  protected rowClass(code: string): string {
    return this.isActive(code)
      ? 'bg-primary/10 border-primary/30 text-primary font-semibold'
      : 'bg-surface-2 border-border-light text-fg hover:bg-surface';
  }

  protected dotClass(code: string): string {
    return this.isActive(code) ? 'bg-primary border-primary' : 'bg-surface border-border-dark';
  }
}
