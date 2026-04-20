import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { QueriesStore } from '../../data/queries.store';
import { ToastService } from '../../core/notifications/toast.service';
import { qtypeById } from '../../data/qtypes.data';
import type { Priority, Query } from '../../shared/models/query';
import { SLA_BY_PRIORITY, type WizardDraft, type WizardStep } from './wizard.model';
import { WizardStepper } from './stepper';
import { WizardStepType } from './step-type';
import { WizardStepDetails } from './step-details';
import { WizardStepReview } from './step-review';
import { WizardSubmitting } from './submitting';
import { WizardSuccess } from './success';

function nextQueryId(existing: readonly Query[]): string {
  const year = new Date().getFullYear();
  const highest = existing.reduce((max, q) => {
    const m = /VQ-\d{4}-(\d+)/.exec(q.id);
    if (!m) return max;
    const n = Number.parseInt(m[1], 10);
    return Number.isFinite(n) && n > max ? n : max;
  }, 0);
  const n = (highest + 1).toString().padStart(4, '0');
  return `VQ-${year}-${n}`;
}

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
            <app-wizard-submitting (done)="onSubmitted()" />
          }
          @case (5) {
            <app-wizard-success
              [queryId]="newId()"
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
              [disabled]="!canAdvance()"
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

  protected readonly step = signal<WizardStep>(1);
  protected readonly type = signal<string>('');
  protected readonly subject = signal<string>('');
  protected readonly desc = signal<string>('');
  protected readonly priority = signal<Priority>('Medium');
  protected readonly ref = signal<string>('');
  protected readonly newId = signal<string>('');

  protected readonly draft = computed<WizardDraft>(() => ({
    type: this.type(),
    subject: this.subject(),
    desc: this.desc(),
    priority: this.priority(),
    ref: this.ref(),
  }));

  protected readonly canAdvance = computed(() => {
    const s = this.step();
    if (s === 1) return this.type().length > 0;
    if (s === 2) {
      return this.subject().trim().length >= 3 && this.desc().trim().length >= 10;
    }
    return true;
  });

  protected next(): void {
    const s = this.step();
    if (s === 3) {
      this.step.set(4);
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
    void this.#router.navigate(['/portal']);
  }

  protected onSubmitted(): void {
    const d = this.draft();
    const t = qtypeById(d.type);
    const id = nextQueryId(this.#store.queries());
    const q: Query = {
      id,
      subj: d.subject || 'New query',
      type: t?.lbl ?? 'Other',
      pri: d.priority,
      status: 'Open',
      submitted: 'Just now',
      sla: SLA_BY_PRIORITY[d.priority],
      slaCls: 'sla-ok',
      agent: 'AI',
      tl: [
        { c: '#10B981', t: 'Query received & logged by VQMS', ts: 'Just now' },
        { c: '#3c2cda', t: `Classified as ${d.priority.toUpperCase()} priority`, ts: '+1s' },
        { c: '#3c2cda', t: 'Routed to the resolution queue', ts: '+4s', p: true },
      ],
      ai: 'Draft pending — AI is preparing a recommended response from the knowledge base.',
      msgs: [{ f: 'vendor', t: d.desc || d.subject, ts: 'Just now' }],
    };
    this.#store.add(q);
    this.newId.set(id);
    this.step.set(5);
    this.#toast.show(`${id} submitted`, 'success');
  }

  protected trackNew(): void {
    const id = this.newId();
    this.resetDraft();
    void this.#router.navigate(['/queries', id]);
  }

  protected reset(): void {
    this.resetDraft();
    this.step.set(1);
  }

  private resetDraft(): void {
    this.type.set('');
    this.subject.set('');
    this.desc.set('');
    this.priority.set('Medium');
    this.ref.set('');
    this.newId.set('');
  }
}
