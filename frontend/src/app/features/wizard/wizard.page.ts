import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';
import { AuthService } from '../../core/auth/auth.service';
import { QueriesStore } from '../../data/queries.store';
import {
  QueryService,
  type BackendPriority,
  type ExtractedEntities,
  type QuerySubmissionPayload,
  type SubmittedAttachment,
} from '../../data/query.service';
import { ToastService } from '../../core/notifications/toast.service';
import { toBackendQueryType } from '../../data/qtypes.data';
import type { Priority } from '../../shared/models/query';
import { type WizardDraft, type WizardStep } from './wizard.model';
import { WizardStepper } from './stepper';
import { WizardStepType } from './step-type';
import { WizardStepDetails } from './step-details';
import { WizardStepReview } from './step-review';
import { WizardSubmitting } from './submitting';
import { WizardSuccess } from './success';

const PRIORITY_TO_BACKEND: Record<Priority, BackendPriority> = {
  Low: 'LOW',
  Medium: 'MEDIUM',
  High: 'HIGH',
  Critical: 'CRITICAL',
};

@Component({
  selector: 'app-wizard-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    WizardStepper,
    WizardStepType,
    WizardStepDetails,
    WizardStepReview,
    WizardSubmitting,
    WizardSuccess,
  ],
  template: `
    <section class="space-y-4 animate-[fade-up_0.3s_ease-out]">
      @if (step() < 4) {
        <div class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm px-5 py-4">
          <div class="flex items-center justify-between mb-4">
            <div class="text-sm font-semibold text-fg">New Query — Step {{ step() }} of 3</div>
            <button
              type="button"
              (click)="cancel()"
              class="text-xs text-fg-dim hover:text-error transition"
            >
              ✕ Cancel
            </button>
          </div>
          <app-wizard-stepper [current]="step()" />
        </div>
      }

      <div class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-6 space-y-4">
        @switch (step()) {
          @case (1) {
            <header class="space-y-1">
              <h2 class="text-lg font-semibold text-fg tracking-tight">Query Type</h2>
              <p class="text-xs text-fg-dim">What kind of issue?</p>
            </header>
            <app-wizard-step-type [(selected)]="type" />
          }
          @case (2) {
            <header class="space-y-1">
              <h2 class="text-lg font-semibold text-fg tracking-tight">Details</h2>
              <p class="text-xs text-fg-dim">Describe your query.</p>
            </header>
            <app-wizard-step-details
              [typeId]="type()"
              [(subject)]="subject"
              [(desc)]="desc"
              [(priority)]="priority"
              [(ref)]="ref"
              [(files)]="files"
              (changeType)="goToStep(1)"
            />
          }
          @case (3) {
            <header class="space-y-1">
              <h2 class="text-lg font-semibold text-fg tracking-tight">Review</h2>
              <p class="text-xs text-fg-dim">Confirm before submitting.</p>
            </header>
            <app-wizard-step-review [draft]="draft()" />
          }
          @case (4) {
            <app-wizard-submitting (done)="onAnimationDone()" />
          }
          @case (5) {
            <app-wizard-success
              [queryId]="newId()"
              [attachments]="submittedAttachments()"
              [entities]="extractedEntities()"
              (track)="trackNew()"
              (newOne)="reset()"
              (done)="cancel()"
            />
          }
        }

        @if (step() < 4) {
          <footer class="flex items-center justify-between pt-4 border-t border-border-light">
            @if (step() > 1) {
              <button
                type="button"
                (click)="back()"
                class="inline-flex items-center gap-1 rounded-[var(--radius-sm)] bg-surface border border-border-light text-xs font-medium text-fg px-3 py-1.5 hover:bg-surface-2 transition"
              >
                ← Back
              </button>
            } @else {
              <button
                type="button"
                (click)="cancel()"
                class="text-xs text-fg-dim hover:text-error transition"
              >
                Cancel
              </button>
            }

            <button
              type="button"
              (click)="next()"
              [disabled]="!canAdvance() || submitting()"
              class="inline-flex items-center gap-1 rounded-[var(--radius-sm)] bg-primary text-surface text-xs font-medium px-4 py-1.5 hover:bg-secondary transition disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {{ step() === 3 ? 'Submit Query →' : 'Continue →' }}
            </button>
          </footer>
        }
      </div>
    </section>
  `,
})
export class WizardPage {
  readonly #router = inject(Router);
  readonly #store = inject(QueriesStore);
  readonly #toast = inject(ToastService);
  readonly #auth = inject(AuthService);
  readonly #svc = inject(QueryService);

  protected readonly step = signal<WizardStep>(1);
  protected readonly type = signal<string>('');
  protected readonly subject = signal<string>('');
  protected readonly desc = signal<string>('');
  protected readonly priority = signal<Priority>('Medium');
  protected readonly ref = signal<string>('');
  protected readonly files = signal<readonly File[]>([]);
  protected readonly newId = signal<string>('');
  protected readonly submitting = signal<boolean>(false);
  protected readonly submittedAttachments = signal<readonly SubmittedAttachment[]>([]);
  protected readonly extractedEntities = signal<ExtractedEntities | null>(null);
  readonly #animationDone = signal<boolean>(false);
  readonly #submissionError = signal<string | null>(null);

  protected readonly draft = computed<WizardDraft>(() => ({
    type: this.type(),
    subject: this.subject(),
    desc: this.desc(),
    priority: this.priority(),
    ref: this.ref(),
    files: this.files(),
  }));

  protected readonly canAdvance = computed(() => {
    const s = this.step();
    if (s === 1) return this.type().length > 0;
    if (s === 2) {
      return this.subject().trim().length >= 5 && this.desc().trim().length >= 10;
    }
    return true;
  });

  protected next(): void {
    const s = this.step();
    if (s === 3) {
      this.#submitToBackend();
      return;
    }
    if (s < 3 && this.canAdvance()) {
      this.step.set((s + 1) as WizardStep);
    }
  }

  protected back(): void {
    const s = this.step();
    if (s > 1 && s < 4) {
      this.step.set((s - 1) as WizardStep);
    }
  }

  protected goToStep(n: WizardStep): void {
    this.step.set(n);
  }

  protected cancel(): void {
    this.resetDraft();
    void this.#router.navigate(this.#auth.vendorPath('portal'));
  }

  protected onAnimationDone(): void {
    this.#animationDone.set(true);
    this.#maybeShowSuccess();
  }

  protected trackNew(): void {
    const id = this.newId();
    this.resetDraft();
    void this.#router.navigate(this.#auth.vendorPath('queries', id));
  }

  protected reset(): void {
    this.resetDraft();
    this.step.set(1);
  }

  #submitToBackend(): void {
    const vendorId = this.#auth.vendorId();
    if (!vendorId) {
      this.#toast.show('You need a vendor profile to submit a query.', 'error');
      return;
    }
    const d = this.draft();
    const payload: QuerySubmissionPayload = {
      query_type: toBackendQueryType(d.type),
      subject: d.subject.trim(),
      description: d.desc.trim(),
      priority: PRIORITY_TO_BACKEND[d.priority],
      reference_number: d.ref.trim() ? d.ref.trim() : null,
    };

    this.submitting.set(true);
    this.newId.set('');
    this.submittedAttachments.set([]);
    this.extractedEntities.set(null);
    this.#animationDone.set(false);
    this.#submissionError.set(null);
    this.step.set(4);

    // vendor_id is no longer passed in the request — the backend reads
    // it from the JWT. We still need vendorId locally to update the
    // queries store with the right vendor on the optimistic insert.
    this.#svc.submit(payload, this.files()).subscribe({
      next: (resp) => {
        this.submitting.set(false);
        this.newId.set(resp.query_id);
        this.submittedAttachments.set(resp.attachments ?? []);
        this.extractedEntities.set(resp.extracted_entities ?? null);
        this.#store.addFromServer({
          query_id: resp.query_id,
          subject: payload.subject,
          query_type: payload.query_type,
          status: resp.status,
          priority: payload.priority,
          source: 'portal',
          processing_path: null,
          reference_number: payload.reference_number ?? null,
          vendor_id: vendorId,
          sla_deadline: null,
          created_at: resp.created_at,
          updated_at: resp.created_at,
        });
        this.#maybeShowSuccess();
      },
      error: (err: unknown) => {
        this.submitting.set(false);
        const msg = this.#errorMessage(err);
        this.#submissionError.set(msg);
        this.#toast.show(msg, 'error', 5000);
        this.step.set(3);
      },
    });
  }

  #maybeShowSuccess(): void {
    if (this.#animationDone() && this.newId()) {
      this.step.set(5);
      this.#toast.show(`${this.newId()} submitted`, 'success');
    }
  }

  #errorMessage(err: unknown): string {
    if (err instanceof HttpErrorResponse) {
      const detail =
        err.error && typeof err.error === 'object' && 'detail' in err.error
          ? (err.error as { detail?: unknown }).detail
          : null;
      if (typeof detail === 'string' && detail.length > 0) return detail;
      if (err.status === 0) return 'Cannot reach the server. Is the backend running?';
      if (err.status === 409) return 'A very similar query was submitted recently (duplicate detected).';
      return `Submission failed (${err.status})`;
    }
    if (err instanceof Error) return err.message;
    return 'Submission failed';
  }

  private resetDraft(): void {
    this.type.set('');
    this.subject.set('');
    this.desc.set('');
    this.priority.set('Medium');
    this.ref.set('');
    this.files.set([]);
    this.newId.set('');
    this.submittedAttachments.set([]);
    this.extractedEntities.set(null);
    this.submitting.set(false);
    this.#animationDone.set(false);
    this.#submissionError.set(null);
  }
}
