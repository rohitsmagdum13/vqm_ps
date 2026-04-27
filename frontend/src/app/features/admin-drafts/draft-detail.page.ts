import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { DomSanitizer, type SafeHtml } from '@angular/platform-browser';
import { toSignal } from '@angular/core/rxjs-interop';
import { DraftApprovalsStore } from '../../data/draft-approvals.store';

type ActionMode = 'idle' | 'editing' | 'rejecting' | 'sending';

@Component({
  selector: 'app-draft-detail-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, DatePipe, FormsModule],
  template: `
    <section class="space-y-6 animate-[fade-up_0.3s_ease-out]">
      @if (detail(); as d) {
        <header
          class="flex items-start justify-between gap-3 flex-wrap rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-5"
        >
          <div class="flex items-start gap-3 min-w-0 flex-1">
            <a
              routerLink="/admin/draft-approvals"
              class="text-fg-dim hover:text-fg text-sm mt-1"
              aria-label="Back to draft queue"
            >←</a>
            <div class="min-w-0">
              <div class="flex items-center gap-2 flex-wrap">
                <h1 class="text-xl font-semibold text-fg tracking-tight">
                  {{ d.subject || '(no subject)' }}
                </h1>
                <span
                  class="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-mono bg-warn/15 text-warn border border-warn/30"
                >{{ d.status }}</span>
              </div>
              <div class="mt-1 text-xs text-fg-dim flex items-center gap-3 flex-wrap">
                <span class="font-mono">{{ d.query_id }}</span>
                <span>·</span>
                <span>drafted {{ d.drafted_at | date: 'MMM d, y, h:mm a' }}</span>
                <span>·</span>
                <span class="font-mono">{{ d.vendor_id || '—' }}</span>
                @if (d.ticket_id) {
                  <span>·</span>
                  <span class="font-mono text-primary">{{ d.ticket_id }}</span>
                }
              </div>
            </div>
          </div>
        </header>

        @if (toast(); as t) {
          <div
            role="status"
            [class]="t.kind === 'ok'
              ? 'rounded-[var(--radius-md)] border border-success/30 bg-success/10 text-success text-xs px-4 py-3'
              : 'rounded-[var(--radius-md)] border border-error/30 bg-error/10 text-error text-xs px-4 py-3'"
          >{{ t.text }}</div>
        }

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <!-- LEFT: original query + AI analysis -->
          <div class="space-y-6">
            <article
              class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-5 space-y-3"
            >
              <header>
                <h2 class="text-sm font-semibold text-fg">Original query</h2>
                <p class="mt-0.5 text-[11px] text-fg-dim">As received from {{ d.source || 'vendor' }}</p>
              </header>
              <div class="rounded-[var(--radius-sm)] bg-surface-2 border border-border-light p-3">
                <div class="text-[11px] text-fg-dim mb-1">Subject</div>
                <div class="text-sm text-fg mb-3">{{ d.subject }}</div>
                <div class="text-[11px] text-fg-dim mb-1">Body</div>
                <p class="text-sm text-fg leading-relaxed whitespace-pre-line">{{ d.original_body }}</p>
              </div>
            </article>

            @if (d.analysis; as a) {
              <article
                class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-5"
              >
                <h2 class="text-sm font-semibold text-fg mb-3">AI analysis</h2>
                <dl class="grid grid-cols-2 gap-3 text-xs">
                  <div>
                    <dt class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">Intent</dt>
                    <dd class="text-fg mt-0.5">{{ a.intent_classification || '—' }}</dd>
                  </div>
                  <div>
                    <dt class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">Category</dt>
                    <dd class="text-fg mt-0.5">{{ a.suggested_category || '—' }}</dd>
                  </div>
                  <div>
                    <dt class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">Urgency</dt>
                    <dd class="text-fg mt-0.5">{{ a.urgency_level || '—' }}</dd>
                  </div>
                  <div>
                    <dt class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">Sentiment</dt>
                    <dd class="text-fg mt-0.5">{{ a.sentiment || '—' }}</dd>
                  </div>
                  <div class="col-span-2">
                    <dt class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">Analysis confidence</dt>
                    <dd class="text-fg mt-0.5 font-mono">{{ a.confidence_score ?? '—' }}</dd>
                  </div>
                </dl>
              </article>
            }

            @if (d.routing; as r) {
              <article
                class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-5"
              >
                <h2 class="text-sm font-semibold text-fg mb-3">Routing</h2>
                <dl class="grid grid-cols-2 gap-3 text-xs">
                  <div>
                    <dt class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">Team</dt>
                    <dd class="text-fg mt-0.5">{{ r.assigned_team || '—' }}</dd>
                  </div>
                  <div>
                    <dt class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">Priority</dt>
                    <dd class="text-fg mt-0.5">{{ r.priority || '—' }}</dd>
                  </div>
                  <div>
                    <dt class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">SLA hours</dt>
                    <dd class="text-fg mt-0.5">{{ r.sla_target?.total_hours ?? '—' }}</dd>
                  </div>
                </dl>
              </article>
            }
          </div>

          <!-- RIGHT: drafted email + actions -->
          <div class="space-y-6">
            <article
              class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-5 space-y-4"
            >
              <header class="flex items-start justify-between gap-2">
                <div>
                  <h2 class="text-sm font-semibold text-fg">Drafted email</h2>
                  <p class="mt-0.5 text-[11px] text-fg-dim">
                    AI draft · ServiceNow ticket already created
                    @if (d.draft.confidence != null) {
                      · confidence
                      <span class="font-mono">{{ d.draft.confidence.toFixed(2) }}</span>
                    }
                  </p>
                </div>
                @if (mode() === 'idle') {
                  <button
                    type="button"
                    (click)="startEdit()"
                    class="text-[11px] text-primary hover:underline"
                  >Edit before sending</button>
                }
              </header>

              @if (mode() === 'editing') {
                <div class="space-y-3">
                  <label class="block">
                    <span class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">Subject</span>
                    <input
                      type="text"
                      [(ngModel)]="editSubject"
                      class="mt-1 w-full rounded-[var(--radius-sm)] border border-border-light bg-surface text-sm text-fg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-primary/40"
                    />
                  </label>
                  <label class="block">
                    <span class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">Body (HTML)</span>
                    <textarea
                      rows="14"
                      [(ngModel)]="editBody"
                      class="mt-1 w-full rounded-[var(--radius-sm)] border border-border-light bg-surface text-sm text-fg font-mono px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary/40"
                    ></textarea>
                  </label>
                </div>
              } @else {
                <div class="space-y-3">
                  <div class="rounded-[var(--radius-sm)] bg-surface-2 border border-border-light p-3">
                    <div class="text-[11px] text-fg-dim mb-1">Subject</div>
                    <div class="text-sm text-fg">{{ d.draft.subject || '(no subject)' }}</div>
                  </div>
                  <div class="rounded-[var(--radius-sm)] bg-surface-2 border border-border-light p-3">
                    <div class="text-[11px] text-fg-dim mb-2">Body preview</div>
                    <div
                      class="prose prose-sm max-w-none text-fg"
                      [innerHTML]="renderedBody()"
                    ></div>
                  </div>
                  @if ((d.draft.sources?.length ?? 0) > 0) {
                    <div class="rounded-[var(--radius-sm)] bg-surface-2 border border-border-light p-3">
                      <div class="text-[11px] text-fg-dim mb-1">KB sources cited</div>
                      <ul class="text-xs text-fg list-disc pl-5 space-y-0.5">
                        @for (src of d.draft.sources; track src) {
                          <li class="font-mono">{{ src }}</li>
                        }
                      </ul>
                    </div>
                  }
                </div>
              }

              @if (mode() === 'rejecting') {
                <div>
                  <label class="block">
                    <span class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">Rejection feedback</span>
                    <textarea
                      rows="4"
                      [(ngModel)]="rejectFeedback"
                      class="mt-1 w-full rounded-[var(--radius-sm)] border border-border-light bg-surface text-sm text-fg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-error/40"
                      placeholder="Why is this draft being rejected?"
                    ></textarea>
                  </label>
                </div>
              }

              <!-- Action bar -->
              <div class="flex items-center justify-end gap-2 pt-2 border-t border-border-light">
                @if (mode() === 'idle') {
                  <button
                    type="button"
                    (click)="startReject()"
                    class="px-3 py-1.5 text-xs font-semibold rounded-[var(--radius-sm)] border border-error/40 text-error hover:bg-error/10"
                  >Reject</button>
                  <button
                    type="button"
                    (click)="approve()"
                    [disabled]="busy()"
                    class="px-3 py-1.5 text-xs font-semibold rounded-[var(--radius-sm)] bg-primary text-surface hover:opacity-90 disabled:opacity-50"
                  >{{ busy() ? 'Sending…' : 'Approve & send' }}</button>
                }
                @if (mode() === 'editing') {
                  <button
                    type="button"
                    (click)="cancelEdit()"
                    class="px-3 py-1.5 text-xs font-semibold rounded-[var(--radius-sm)] border border-border-light text-fg-dim hover:bg-surface-2"
                  >Cancel</button>
                  <button
                    type="button"
                    (click)="approveWithEdits()"
                    [disabled]="busy() || !editSubject().trim() || !editBody().trim()"
                    class="px-3 py-1.5 text-xs font-semibold rounded-[var(--radius-sm)] bg-primary text-surface hover:opacity-90 disabled:opacity-50"
                  >{{ busy() ? 'Sending…' : 'Save & send' }}</button>
                }
                @if (mode() === 'rejecting') {
                  <button
                    type="button"
                    (click)="cancelReject()"
                    class="px-3 py-1.5 text-xs font-semibold rounded-[var(--radius-sm)] border border-border-light text-fg-dim hover:bg-surface-2"
                  >Cancel</button>
                  <button
                    type="button"
                    (click)="confirmReject()"
                    [disabled]="busy() || !rejectFeedback().trim()"
                    class="px-3 py-1.5 text-xs font-semibold rounded-[var(--radius-sm)] bg-error text-surface hover:opacity-90 disabled:opacity-50"
                  >{{ busy() ? 'Saving…' : 'Confirm reject' }}</button>
                }
              </div>
            </article>
          </div>
        </div>
      } @else {
        <div
          class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-10 text-center"
        >
          <p class="text-sm text-fg-dim">
            @if (loading()) { Loading draft… } @else { Draft not found. }
          </p>
          <a
            routerLink="/admin/draft-approvals"
            class="inline-block mt-3 text-xs font-semibold text-primary hover:underline"
          >← Back to queue</a>
        </div>
      }
    </section>
  `,
})
export class DraftDetailPage {
  readonly #store = inject(DraftApprovalsStore);
  readonly #route = inject(ActivatedRoute);
  readonly #router = inject(Router);
  readonly #sanitizer = inject(DomSanitizer);

  readonly #queryIdParam = toSignal(this.#route.paramMap, {
    initialValue: this.#route.snapshot.paramMap,
  });

  protected readonly detail = this.#store.detail;
  protected readonly loading = this.#store.loading;

  protected readonly mode = signal<ActionMode>('idle');
  protected readonly busy = computed<boolean>(() => this.mode() === 'sending');
  protected readonly toast = signal<{ kind: 'ok' | 'err'; text: string } | null>(null);

  protected readonly editSubject = signal<string>('');
  protected readonly editBody = signal<string>('');
  protected readonly rejectFeedback = signal<string>('');

  /**
   * Render the drafted body as HTML. The body originates from the LLM
   * via the Quality Gate which already enforces format / restricted-term
   * checks server-side, but we still bypass Angular's auto-sanitiser
   * intentionally because the email body legitimately contains links
   * and inline markup that the default sanitiser would strip.
   */
  protected readonly renderedBody = computed<SafeHtml>(() => {
    const html = this.detail()?.draft.body ?? '';
    return this.#sanitizer.bypassSecurityTrustHtml(html);
  });

  // Track which query_id we've already loaded so we don't refetch on
  // every change-detection pass.
  readonly #loadedIds = new Set<string>();

  constructor() {
    effect(() => {
      const id = this.#queryIdParam().get('id');
      if (!id || this.#loadedIds.has(id)) return;
      this.#loadedIds.add(id);
      void this.#store.loadDetail(id);
    });
  }

  protected startEdit(): void {
    const d = this.detail();
    if (!d) return;
    this.editSubject.set(d.draft.subject ?? '');
    this.editBody.set(d.draft.body ?? '');
    this.mode.set('editing');
  }

  protected cancelEdit(): void {
    this.mode.set('idle');
  }

  protected startReject(): void {
    this.rejectFeedback.set('');
    this.mode.set('rejecting');
  }

  protected cancelReject(): void {
    this.mode.set('idle');
  }

  protected async approve(): Promise<void> {
    const d = this.detail();
    if (!d) return;
    this.mode.set('sending');
    const ok = await this.#store.approve(d.query_id);
    if (ok) {
      this.toast.set({ kind: 'ok', text: 'Draft approved and email sent.' });
      void this.#router.navigate(['/admin/draft-approvals']);
    } else {
      this.toast.set({ kind: 'err', text: this.#store.error() ?? 'Approve failed.' });
      this.mode.set('idle');
    }
  }

  protected async approveWithEdits(): Promise<void> {
    const d = this.detail();
    if (!d) return;
    this.mode.set('sending');
    const ok = await this.#store.approveWithEdits(d.query_id, {
      subject: this.editSubject().trim(),
      body_html: this.editBody().trim(),
    });
    if (ok) {
      this.toast.set({ kind: 'ok', text: 'Edited draft sent to vendor.' });
      void this.#router.navigate(['/admin/draft-approvals']);
    } else {
      this.toast.set({ kind: 'err', text: this.#store.error() ?? 'Save & send failed.' });
      this.mode.set('editing');
    }
  }

  protected async confirmReject(): Promise<void> {
    const d = this.detail();
    if (!d) return;
    this.mode.set('sending');
    const ok = await this.#store.reject(d.query_id, this.rejectFeedback().trim());
    if (ok) {
      this.toast.set({ kind: 'ok', text: 'Draft rejected.' });
      void this.#router.navigate(['/admin/draft-approvals']);
    } else {
      this.toast.set({ kind: 'err', text: this.#store.error() ?? 'Reject failed.' });
      this.mode.set('rejecting');
    }
  }
}
