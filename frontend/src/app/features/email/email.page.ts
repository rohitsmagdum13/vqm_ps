import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { EmailsStore } from '../../data/emails.store';
import { SpinnerComponent } from '../../shared/ui/spinner/spinner';
import { FilterRail } from './filter-rail';
import { SummaryCards } from './summary-cards';
import { MessageList } from './message-list';
import { MessageViewer } from './message-viewer';

@Component({
  selector: 'app-email-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [SpinnerComponent, FilterRail, SummaryCards, MessageList, MessageViewer],
  template: `
    <section class="flex flex-col gap-5 animate-[fade-up_0.3s_ease-out] h-[calc(100vh-8rem)]">
      <header
        class="flex items-start justify-between gap-4 flex-wrap rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-5"
      >
        <div class="flex items-start gap-3">
          <div
            class="h-10 w-10 shrink-0 rounded-full bg-primary/10 text-primary flex items-center justify-center text-lg"
            aria-hidden="true"
          >
            ✉️
          </div>
          <div>
            <h1 class="text-xl font-semibold text-fg tracking-tight">Email</h1>
            <p class="mt-1 text-xs text-fg-dim">
              Inbox linked with VQMS queries — triage, filter, and resolve vendor conversations.
            </p>
          </div>
        </div>
        <div class="flex items-center gap-2">
          @if (loading() && hasLoaded()) {
            <ui-spinner size="sm" label="Refreshing" />
          }
          <button
            type="button"
            (click)="refresh()"
            [disabled]="loading()"
            class="inline-flex items-center gap-2 rounded-[var(--radius-sm)] border border-border-light text-fg text-xs font-semibold px-3 py-2 hover:bg-surface-2 disabled:opacity-50 transition"
          >↻ Refresh</button>
        </div>
      </header>

      @if (error(); as err) {
        <div
          role="alert"
          class="rounded-[var(--radius-md)] border border-error/30 bg-error/10 text-error text-xs px-4 py-3"
        >
          Failed to load email: {{ err }}
          <button
            type="button"
            (click)="refresh()"
            class="ml-2 underline hover:no-underline"
          >Retry</button>
        </div>
      }

      <app-summary-cards />

      @if (!hasLoaded() && loading()) {
        <div class="py-16 flex justify-center">
          <ui-spinner size="lg" label="Loading mail" />
        </div>
      } @else {
        <div class="grid grid-cols-1 lg:grid-cols-[220px_minmax(0,1fr)_minmax(0,1.35fr)] gap-6 flex-1 min-h-0">
          <app-filter-rail />
          <app-message-list />
          <app-message-viewer />
        </div>
      }
    </section>
  `,
})
export class EmailPage {
  readonly #store = inject(EmailsStore);
  protected readonly loading = this.#store.loading;
  protected readonly hasLoaded = this.#store.hasLoaded;
  protected readonly error = this.#store.error;

  constructor() {
    if (!this.#store.hasLoaded()) {
      this.#store.refresh();
    }
  }

  protected refresh(): void {
    this.#store.refresh();
  }
}
