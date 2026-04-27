import { ChangeDetectionStrategy, Component, computed, effect, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { AuthService } from '../../../core/auth/auth.service';
import { QueriesStore } from '../../../data/queries.store';
import { ToastService } from '../../../core/notifications/toast.service';
import { BadgeComponent } from '../../../shared/ui/badge/badge';
import { priorityTone, statusTone } from '../../../shared/ui/badge/badge-tones';
import type { MessageAuthor } from '../../../shared/models/query';
import { PipelineTimeline } from './pipeline-timeline';

@Component({
  selector: 'app-query-detail-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, ReactiveFormsModule, BadgeComponent, PipelineTimeline],
  template: `
    <section class="space-y-6 animate-[fade-up_0.3s_ease-out]">
      <div class="flex items-center justify-between">
        <a
          [routerLink]="backLink()"
          class="inline-flex items-center gap-1 text-sm text-fg-dim hover:text-primary transition"
        >
          <span aria-hidden="true">←</span> Back to queries
        </a>
      </div>

      @if (query(); as q) {
        <header class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-5 space-y-3">
          <div class="flex items-start justify-between gap-4 flex-wrap">
            <div class="min-w-0">
              <div class="font-mono text-[11px] text-fg-dim">{{ q.id }}</div>
              <h1 class="mt-1 text-xl font-semibold text-fg tracking-tight">{{ q.subj }}</h1>
            </div>
            <div class="flex items-center gap-2 flex-wrap">
              <ui-badge [tone]="statusTone(q.status)">{{ q.status }}</ui-badge>
              <ui-badge [tone]="priorityTone(q.pri)">{{ q.pri }}</ui-badge>
              @if (q.slaCls === 'sla-brch') {
                <ui-badge tone="error">SLA Breached</ui-badge>
              }
            </div>
          </div>

          <dl class="grid grid-cols-2 sm:grid-cols-3 gap-3 pt-3 border-t border-border-light">
            <div>
              <dt class="text-[10px] font-mono tracking-wider uppercase text-fg-dim">Type</dt>
              <dd class="mt-1 text-sm text-fg">{{ q.type }}</dd>
            </div>
            <div>
              <dt class="text-[10px] font-mono tracking-wider uppercase text-fg-dim">Submitted</dt>
              <dd class="mt-1 text-sm text-fg">{{ q.submitted }}</dd>
            </div>
            <div>
              <dt class="text-[10px] font-mono tracking-wider uppercase text-fg-dim">SLA</dt>
              <dd class="mt-1 text-sm font-mono" [class]="slaClass(q.slaCls)">{{ q.sla }}</dd>
            </div>
          </dl>
        </header>

        <app-pipeline-timeline
          [events]="trail()"
          [polling]="isPipelineActive()"
          [showDetails]="isAdmin()"
        />

        <section
          class="rounded-[var(--radius-md)] border border-success/20 p-4 space-y-2 bg-gradient-to-br from-success/5 to-primary/5"
        >
          <div class="flex items-center gap-2 text-[10px] font-mono tracking-wider uppercase text-success">
            <span class="inline-block h-2 w-2 rounded-full bg-success"></span>
            AI draft · Confidence 94%
          </div>
          <p class="text-sm leading-relaxed text-fg">{{ q.ai }}</p>
        </section>

        <section class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-5">
          <h2 class="text-[10px] font-mono tracking-wider uppercase text-fg-dim mb-4">
            Communication Thread
          </h2>
          <div class="space-y-3">
            @for (m of q.msgs; track $index) {
              <div [class]="rowAlign(m.f)">
                <div class="max-w-[75%]" [class]="bubbleAlign(m.f)">
                  <div class="rounded-[var(--radius-md)] border px-3 py-2 text-sm leading-relaxed" [class]="bubbleClass(m.f)">
                    @if (m.f === 'ai') {
                      <div class="flex items-center gap-1 text-[10px] font-mono tracking-wider uppercase text-success mb-1">
                        <span class="inline-block h-1.5 w-1.5 rounded-full bg-success"></span>
                        AI Assistant
                      </div>
                    }
                    {{ m.t }}
                  </div>
                  <div class="mt-1 text-[10px] font-mono text-fg-dim" [class]="metaAlign(m.f)">
                    @if (m.f === 'vendor') { You · }{{ m.ts }}
                  </div>
                </div>
              </div>
            }
          </div>

          <form
            class="mt-5 pt-4 border-t border-border-light flex flex-col gap-2"
            (ngSubmit)="sendReply()"
          >
            <label for="reply" class="text-[10px] font-mono tracking-wider uppercase text-fg-dim">
              Your reply
            </label>
            <textarea
              id="reply"
              rows="3"
              [formControl]="reply"
              placeholder="Type your reply…"
              class="w-full rounded-[var(--radius-sm)] bg-surface-2 border border-border-light text-sm text-fg px-3 py-2 focus:outline-none focus:border-primary resize-y"
            ></textarea>
            <div class="flex items-center justify-end gap-2">
              <button
                type="submit"
                [disabled]="reply.invalid || sending()"
                class="inline-flex items-center gap-1 rounded-[var(--radius-sm)] bg-primary text-surface text-xs font-medium px-3 py-1.5 hover:bg-secondary transition disabled:opacity-50 disabled:cursor-not-allowed"
              >
                @if (sending()) { Sending… } @else { Send reply → }
              </button>
            </div>
          </form>
        </section>
      } @else {
        <div
          class="rounded-[var(--radius-md)] border border-dashed border-border-light bg-surface p-8 text-center space-y-2"
        >
          <div class="text-sm text-fg">Query not found</div>
          <div class="text-xs text-fg-dim">The query ID <span class="font-mono">{{ id() }}</span> is unknown.</div>
        </div>
      }
    </section>
  `,
})
export class QueryDetailPage {
  readonly #store = inject(QueriesStore);
  readonly #toast = inject(ToastService);
  readonly #auth = inject(AuthService);
  readonly #params = toSignal(inject(ActivatedRoute).paramMap);

  protected readonly id = computed(() => this.#params()?.get('id') ?? '');
  protected readonly query = computed(() => this.#store.selected());
  protected readonly trail = computed(() => this.#store.trail());
  protected readonly sending = signal(false);
  protected readonly isAdmin = computed(() => this.#auth.role() === 'admin');
  protected readonly backLink = computed<string[]>(() =>
    this.isAdmin() ? ['/admin/queries'] : this.#auth.vendorPath('queries'),
  );
  // The `<app-pipeline-timeline>` shows a "live" badge while polling.
  // Treat the query as in-flight unless it has reached a terminal state.
  protected readonly isPipelineActive = computed(() => {
    const status = this.query()?.status;
    return status !== 'Resolved' && status !== 'Breached';
  });

  constructor() {
    effect(() => {
      const target = this.id();
      if (target) this.#store.loadDetail(target);
    });
  }

  protected readonly reply = new FormControl<string>('', {
    nonNullable: true,
    validators: [Validators.required, Validators.minLength(1)],
  });

  protected readonly statusTone = statusTone;
  protected readonly priorityTone = priorityTone;

  protected slaClass(cls: 'sla-ok' | 'sla-brch'): string {
    return cls === 'sla-brch' ? 'text-error' : 'text-success';
  }

  protected rowAlign(f: MessageAuthor): string {
    return f === 'vendor' ? 'flex justify-end' : 'flex justify-start';
  }

  protected bubbleAlign(f: MessageAuthor): string {
    return f === 'vendor' ? 'items-end text-right' : 'items-start';
  }

  protected metaAlign(f: MessageAuthor): string {
    return f === 'vendor' ? 'text-right' : 'text-left';
  }

  protected bubbleClass(f: MessageAuthor): string {
    switch (f) {
      case 'vendor':
        return 'bg-primary/10 text-fg border-primary/20';
      case 'ai':
        return 'bg-success/8 border-success/20';
      case 'us':
        return 'bg-surface-2 border-border-light';
    }
  }

  protected sendReply(): void {
    const text = this.reply.value.trim();
    const id = this.id();
    if (!text || !id) return;
    this.sending.set(true);
    this.#store.appendMessage(id, { f: 'vendor', t: text, ts: 'Just now' });
    this.reply.reset('');
    this.sending.set(false);
    this.#toast.show('Reply sent', 'success');
  }
}
