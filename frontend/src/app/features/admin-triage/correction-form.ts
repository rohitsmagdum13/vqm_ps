import { ChangeDetectionStrategy, Component, inject, input, output } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { ToastService } from '../../core/notifications/toast.service';
import { TriageStore } from '../../data/triage.store';
import type { ReviewerDecision, TriageCase } from '../../shared/models/triage';

const TEAMS: ReadonlyArray<ReviewerDecision['assigned_team']> = [
  'AP-FINANCE',
  'PROCUREMENT',
  'LOGISTICS',
  'COMPLIANCE',
  'TECH-SUPPORT',
];

const INTENT_OPTIONS: readonly string[] = [
  'invoice_status',
  'invoice_dispute',
  'po_amendment',
  'payment_terms_query',
  'banking_update',
  'delivery_delay',
  'compliance_query',
  'contract_query',
  'general_inquiry',
  'multi_issue',
];

const CATEGORY_OPTIONS: readonly string[] = [
  'invoicing',
  'procurement',
  'logistics',
  'compliance',
  'payments',
  'contract',
  'general',
];

@Component({
  selector: 'app-correction-form',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  template: `
    <article
      class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-5 space-y-4"
    >
      <header>
        <h2 class="text-sm font-semibold text-fg">Reviewer correction</h2>
        <p class="mt-0.5 text-[11px] text-fg-dim">
          Submit corrected classification to resume the workflow. SLA clock starts after submission.
        </p>
      </header>

      <form [formGroup]="form" (ngSubmit)="submit()" class="space-y-3">
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <label class="space-y-1">
            <span class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">
              Corrected intent
            </span>
            <select
              formControlName="corrected_intent"
              class="w-full text-sm bg-surface-2 border border-border-light rounded-[var(--radius-sm)] px-3 py-2 outline-none focus:border-primary/40"
            >
              @for (opt of intentOptions; track opt) {
                <option [value]="opt">{{ opt }}</option>
              }
            </select>
          </label>

          <label class="space-y-1">
            <span class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">
              Corrected category
            </span>
            <select
              formControlName="corrected_category"
              class="w-full text-sm bg-surface-2 border border-border-light rounded-[var(--radius-sm)] px-3 py-2 outline-none focus:border-primary/40"
            >
              @for (opt of categoryOptions; track opt) {
                <option [value]="opt">{{ opt }}</option>
              }
            </select>
          </label>
        </div>

        <label class="block space-y-1">
          <span class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">
            Assigned team
          </span>
          <div class="flex flex-wrap gap-2">
            @for (team of teams; track team) {
              <button
                type="button"
                (click)="setTeam(team)"
                [class]="form.value.assigned_team === team
                  ? 'px-3 py-1.5 text-xs font-semibold rounded-[var(--radius-sm)] bg-primary text-surface'
                  : 'px-3 py-1.5 text-xs font-medium rounded-[var(--radius-sm)] bg-surface-2 text-fg-dim border border-border-light hover:text-fg'"
              >{{ team }}</button>
            }
          </div>
        </label>

        <label class="block space-y-1">
          <span class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">
            Reviewer notes
          </span>
          <textarea
            formControlName="notes"
            rows="3"
            placeholder="Optional notes about the correction (used in audit log)…"
            class="w-full text-sm bg-surface-2 border border-border-light rounded-[var(--radius-sm)] px-3 py-2 outline-none focus:border-primary/40 resize-none"
          ></textarea>
        </label>

        <div class="flex items-center justify-between gap-3 pt-2">
          <p class="text-[11px] text-fg-dim">
            Resuming will re-run KB search + routing with these values.
          </p>
          <button
            type="submit"
            [disabled]="form.invalid || submitted()"
            class="inline-flex items-center gap-2 rounded-[var(--radius-sm)] bg-primary text-surface text-xs font-semibold px-4 py-2 hover:bg-primary/90 transition disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <span>Submit & resume workflow</span>
            <span aria-hidden="true">→</span>
          </button>
        </div>
      </form>

      @if (submitted()) {
        <div
          role="status"
          class="rounded-[var(--radius-sm)] bg-success/10 border border-success/30 text-success text-xs px-3 py-2"
        >Decision submitted. Workflow resumed.</div>
      }
    </article>
  `,
})
export class CorrectionForm {
  readonly case = input.required<TriageCase>();
  readonly submittedChange = output<ReviewerDecision>();

  readonly #store = inject(TriageStore);
  readonly #toast = inject(ToastService);

  protected readonly intentOptions = INTENT_OPTIONS;
  protected readonly categoryOptions = CATEGORY_OPTIONS;
  protected readonly teams = TEAMS;

  protected readonly form = new FormGroup({
    corrected_intent: new FormControl<string>('invoice_status', {
      nonNullable: true,
      validators: [Validators.required],
    }),
    corrected_category: new FormControl<string>('invoicing', {
      nonNullable: true,
      validators: [Validators.required],
    }),
    assigned_team: new FormControl<ReviewerDecision['assigned_team']>('AP-FINANCE', {
      nonNullable: true,
      validators: [Validators.required],
    }),
    notes: new FormControl<string>('', { nonNullable: true }),
  });

  protected submitted(): boolean {
    return !!this.#store.decisionFor(this.case().query_id);
  }

  protected setTeam(team: ReviewerDecision['assigned_team']): void {
    this.form.patchValue({ assigned_team: team });
  }

  protected submit(): void {
    if (this.form.invalid || this.submitted()) return;

    const decision: ReviewerDecision = {
      query_id: this.case().query_id,
      corrected_intent: this.form.controls.corrected_intent.value,
      corrected_category: this.form.controls.corrected_category.value,
      assigned_team: this.form.controls.assigned_team.value,
      notes: this.form.controls.notes.value,
    };

    this.#store.submitDecision(decision);
    this.#toast.show(`Decision submitted for ${decision.query_id}`, 'success');
    this.submittedChange.emit(decision);
  }
}
