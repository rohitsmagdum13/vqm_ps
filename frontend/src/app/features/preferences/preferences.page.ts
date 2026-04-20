import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { PreferencesStore } from '../../data/preferences.store';
import { ToastService } from '../../core/notifications/toast.service';
import { PrefNav } from './pref-nav';
import { ProfileBox } from './profile-box';
import { ToggleRow } from './toggle-row';
import { LanguagePanel } from './language-panel';
import { PREF_TOGGLES, type PrefSection, type PrefToggleRow } from './preferences.data';

const SECTION_META: Readonly<Record<PrefSection, { readonly title: string; readonly sub: string }>> = {
  profile: { title: 'Profile', sub: 'Your identity and security settings.' },
  notifications: { title: 'Notifications', sub: 'Decide when VQMS should reach out.' },
  sla: { title: 'SLA alerts', sub: 'Stay ahead of breach deadlines.' },
  language: { title: 'Language', sub: 'Choose the portal display language.' },
};

@Component({
  selector: 'app-preferences-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [PrefNav, ProfileBox, ToggleRow, LanguagePanel],
  template: `
    <section class="space-y-6 animate-[fade-up_0.3s_ease-out]">
      <header
        class="flex items-start justify-between gap-4 flex-wrap rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-5"
      >
        <div class="flex items-start gap-3">
          <div
            class="h-10 w-10 shrink-0 rounded-full bg-primary/10 text-primary flex items-center justify-center text-lg"
            aria-hidden="true"
          >
            ⚙️
          </div>
          <div>
            <h1 class="text-xl font-semibold text-fg tracking-tight">Preferences</h1>
            <p class="mt-1 text-xs text-fg-dim">
              Tailor VQMS alerts, language, and profile visibility.
            </p>
          </div>
        </div>
      </header>

      <div class="grid grid-cols-1 md:grid-cols-[220px_minmax(0,1fr)] gap-8">
        <app-pref-nav [(active)]="section" />

        <article
          class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-5 space-y-4"
        >
          <div>
            <h2 class="text-sm font-semibold text-fg">{{ meta().title }}</h2>
            <p class="mt-0.5 text-[11px] text-fg-dim">{{ meta().sub }}</p>
          </div>

          @if (section() === 'profile') {
            <app-profile-box />
            <div class="space-y-2">
              @for (row of profileToggles(); track row.id) {
                <app-toggle-row [row]="row" />
              }
            </div>
          }

          @if (section() === 'notifications') {
            <div class="space-y-2">
              @for (row of notifToggles(); track row.id) {
                <app-toggle-row [row]="row" />
              }
            </div>
          }

          @if (section() === 'sla') {
            <div class="space-y-2">
              @for (row of slaToggles(); track row.id) {
                <app-toggle-row [row]="row" />
              }
            </div>
          }

          @if (section() === 'language') {
            <app-language-panel />
          }

          <div class="flex flex-wrap items-center justify-end gap-2 pt-2">
            @if (store.dirty()) {
              <span class="mr-auto text-[11px] text-warn font-mono uppercase tracking-wider">
                Unsaved changes
              </span>
            }
            <button
              type="button"
              (click)="discard()"
              [disabled]="!store.dirty()"
              class="inline-flex items-center rounded-[var(--radius-sm)] border border-border-light px-3 py-1.5 text-xs font-medium text-fg hover:bg-surface-2 transition disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Discard
            </button>
            <button
              type="button"
              (click)="save()"
              [disabled]="!store.dirty()"
              class="inline-flex items-center rounded-[var(--radius-sm)] bg-primary text-surface px-3 py-1.5 text-xs font-semibold hover:bg-primary/90 transition disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Save preferences
            </button>
          </div>
        </article>
      </div>
    </section>
  `,
})
export class PreferencesPage {
  protected readonly store = inject(PreferencesStore);
  readonly #toast = inject(ToastService);

  protected readonly section = signal<PrefSection>('profile');
  protected readonly meta = computed(() => SECTION_META[this.section()]);

  protected readonly profileToggles = computed<readonly PrefToggleRow[]>(() =>
    PREF_TOGGLES.filter((t) => t.section === 'profile'),
  );
  protected readonly notifToggles = computed<readonly PrefToggleRow[]>(() =>
    PREF_TOGGLES.filter((t) => t.section === 'notifications'),
  );
  protected readonly slaToggles = computed<readonly PrefToggleRow[]>(() =>
    PREF_TOGGLES.filter((t) => t.section === 'sla'),
  );

  protected save(): void {
    this.store.commit();
    this.#toast.show('Preferences saved', 'success');
  }

  protected discard(): void {
    this.store.discard();
    this.#toast.show('Changes discarded', 'info');
  }
}
