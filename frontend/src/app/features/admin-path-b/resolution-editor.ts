import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { ToastService } from '../../core/notifications/toast.service';
import { PathBStore } from '../../data/path-b.store';
import type { PathBTicket } from '../../shared/models/path-b';

const MIN_NOTES_LENGTH = 30;

@Component({
  selector: 'app-resolution-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  template: `
    <article
      class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-5 space-y-3"
    >
      <header class="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h2 class="text-sm font-semibold text-fg">Resolution notes</h2>
          <p class="mt-0.5 text-[11px] text-fg-dim">
            These notes feed into <span class="font-mono">LLM Call #3</span>, which drafts the resolution email to the vendor.
          </p>
        </div>
        @if (ticket().status === 'RESOLVED') {
          <span
            class="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold bg-success/15 text-success border border-success/30"
          >Resolved</span>
        }
      </header>

      <textarea
        [formControl]="ctrl"
        rows="10"
        placeholder="Investigation findings:&#10;• …&#10;&#10;Resolution:&#10;• …"
        class="w-full text-sm bg-surface-2 border border-border-light rounded-[var(--radius-sm)] px-3 py-2 outline-none focus:border-primary/40 resize-y font-mono leading-relaxed"
        [disabled]="ticket().status === 'RESOLVED'"
      ></textarea>

      <div class="flex items-center justify-between text-[11px] text-fg-dim">
        <span>{{ charCountLabel() }}</span>
        <span>{{ saveStatusLabel() }}</span>
      </div>

      <div class="flex items-center justify-between gap-3 pt-2 border-t border-border-light">
        <p class="text-[11px] text-fg-dim">
          Marking resolved triggers the AI resolution email to the vendor.
        </p>
        <div class="flex gap-2">
          <button
            type="button"
            (click)="saveDraft()"
            [disabled]="ticket().status === 'RESOLVED' || ctrlValue().length === 0"
            class="text-xs font-semibold text-fg-dim hover:text-fg disabled:opacity-50 disabled:cursor-not-allowed px-3 py-2"
          >Save draft</button>
          <button
            type="button"
            (click)="markResolved()"
            [disabled]="!canResolve()"
            class="inline-flex items-center gap-2 rounded-[var(--radius-sm)] bg-primary text-surface text-xs font-semibold px-4 py-2 hover:bg-primary/90 transition disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <span>Mark resolved & trigger email</span>
            <span aria-hidden="true">→</span>
          </button>
        </div>
      </div>
    </article>
  `,
})
export class ResolutionEditor {
  readonly ticket = input.required<PathBTicket>();
  readonly draftToInsert = input<string>('');

  readonly #store = inject(PathBStore);
  readonly #toast = inject(ToastService);

  protected readonly ctrl = new FormControl<string>('', { nonNullable: true });
  protected readonly ctrlValue = signal<string>('');
  readonly #lastSavedValue = signal<string>('');

  protected readonly charCountLabel = computed<string>(() => {
    const len = this.ctrlValue().length;
    return `${len} character${len === 1 ? '' : 's'}`;
  });

  protected readonly canResolve = computed<boolean>(() => {
    if (this.ticket().status === 'RESOLVED') return false;
    return this.ctrlValue().trim().length >= MIN_NOTES_LENGTH;
  });

  protected readonly saveStatusLabel = computed<string>(() => {
    if (this.ticket().status === 'RESOLVED') return 'Sealed (resolved)';
    if (this.ctrlValue() === this.#lastSavedValue() && this.#lastSavedValue().length > 0) {
      return 'Saved';
    }
    if (this.ctrlValue().trim().length < MIN_NOTES_LENGTH) {
      return `${MIN_NOTES_LENGTH - this.ctrlValue().trim().length} more chars to enable resolve`;
    }
    return 'Unsaved changes';
  });

  constructor() {
    // Sync form control value into a signal for computed derivations.
    this.ctrl.valueChanges.subscribe((v) => this.ctrlValue.set(v));

    // Initialize the editor with whatever notes are already on the ticket.
    effect(() => {
      const t = this.ticket();
      const current = this.ctrl.value;
      // Only seed once per ticket so we don't clobber the user's typing.
      if (current === '' && t.resolution_notes.length > 0) {
        this.ctrl.setValue(t.resolution_notes);
        this.#lastSavedValue.set(t.resolution_notes);
      }
    });

    // When the parent passes a draft (from copilot "Use draft →"), insert it.
    effect(() => {
      const draft = this.draftToInsert();
      if (!draft) return;
      const existing = this.ctrl.value.trim();
      const merged = existing.length > 0 ? `${existing}\n\n${draft}` : draft;
      this.ctrl.setValue(merged);
    });
  }

  protected saveDraft(): void {
    const val = this.ctrl.value;
    this.#store.saveNotes(this.ticket().ticket_id, val);
    this.#lastSavedValue.set(val);
    this.#toast.show('Draft saved', 'success');
  }

  protected markResolved(): void {
    if (!this.canResolve()) return;
    const val = this.ctrl.value;
    this.#store.markResolved(this.ticket().ticket_id, val);
    this.#lastSavedValue.set(val);
    this.#toast.show(
      `Ticket ${this.ticket().ticket_id} resolved. Resolution email queued.`,
      'success',
    );
  }
}
