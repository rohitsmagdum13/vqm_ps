import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { CopilotService } from '../../data/copilot.service';
import type { CopilotMessage } from '../../shared/models/triage';

const SUGGESTED_PROMPTS: ReadonlyArray<string> = [
  'Why did the AI flag this as low confidence? Which team should I route to?',
  "What's this vendor's recent history? Any patterns I should be aware of?",
  'Are there any open tickets that this query might be related to?',
  'What should I ask the vendor to clarify before processing this?',
];

@Component({
  selector: 'app-copilot-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  template: `
    <article
      class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm flex flex-col h-[640px]"
    >
      <header class="px-5 py-3 border-b border-border-light flex items-center justify-between">
        <div class="flex items-center gap-2.5">
          <div
            class="h-8 w-8 rounded-full bg-primary/10 text-primary flex items-center justify-center text-sm"
            aria-hidden="true"
          >🤖</div>
          <div>
            <h2 class="text-sm font-semibold text-fg leading-none">Reviewer Copilot</h2>
            <p class="text-[10px] text-fg-dim mt-0.5">MCP-powered · Path C investigation assistant</p>
          </div>
        </div>
        @if (messages().length > 0) {
          <button
            type="button"
            (click)="reset()"
            class="text-[11px] text-fg-dim hover:text-fg"
            aria-label="Clear conversation"
          >Clear</button>
        }
      </header>

      <div class="flex-1 overflow-y-auto px-5 py-4 space-y-3">
        @if (messages().length === 0 && !busy()) {
          <div class="text-center text-fg-dim text-xs py-8 space-y-3">
            <div class="text-3xl" aria-hidden="true">💬</div>
            <p>Ask the copilot anything about this query.</p>
            <div class="flex flex-col gap-1.5 max-w-[400px] mx-auto">
              @for (p of suggestedPrompts; track p) {
                <button
                  type="button"
                  (click)="sendPrompt(p)"
                  class="text-left text-xs px-3 py-2 rounded-[var(--radius-sm)] bg-surface-2 hover:bg-primary/8 hover:text-fg border border-border-light transition"
                >{{ p }}</button>
              }
            </div>
          </div>
        }

        @for (m of messages(); track m.id) {
          @switch (m.role) {
            @case ('reviewer') {
              <div class="flex justify-end">
                <div class="max-w-[80%] rounded-[var(--radius-sm)] bg-primary text-surface px-3 py-2 text-sm">
                  {{ m.content }}
                  <div class="text-[10px] opacity-70 mt-1 text-right">{{ m.timestamp }}</div>
                </div>
              </div>
            }
            @case ('agent_thought') {
              <div class="flex items-start gap-2 text-fg-dim">
                <span class="text-xs mt-1" aria-hidden="true">💭</span>
                <p class="text-xs italic leading-snug">{{ m.content }}</p>
              </div>
            }
            @case ('tool_call') {
              <div class="rounded-[var(--radius-sm)] bg-surface-2 border border-border-light px-3 py-2 text-xs font-mono">
                <div class="text-primary font-semibold flex items-center gap-1.5">
                  <span aria-hidden="true">⚙</span>
                  <span>{{ m.tool_name }}</span>
                </div>
                <div class="text-fg-dim mt-1 break-all">
                  {{ argsLabel(m.tool_args) }}
                </div>
              </div>
            }
            @case ('tool_result') {
              <div class="rounded-[var(--radius-sm)] bg-success/8 border border-success/20 px-3 py-2 text-xs">
                <div class="text-success font-semibold text-[10px] uppercase tracking-wider mb-1">
                  Result · {{ m.tool_name }}
                </div>
                <div class="text-fg leading-snug">{{ m.content }}</div>
              </div>
            }
            @case ('agent_final') {
              <div class="rounded-[var(--radius-md)] bg-primary/5 border border-primary/30 px-4 py-3">
                <div class="text-primary font-semibold text-[10px] uppercase tracking-wider mb-2 flex items-center gap-1.5">
                  <span aria-hidden="true">✨</span>
                  <span>Recommendation</span>
                </div>
                <pre class="text-xs leading-relaxed text-fg whitespace-pre-wrap font-sans">{{ m.content }}</pre>
                <div class="text-[10px] text-fg-dim mt-2 text-right">{{ m.timestamp }}</div>
              </div>
            }
          }
        }

        @if (busy()) {
          <div class="flex items-center gap-2 text-xs text-fg-dim">
            <span class="inline-flex gap-1">
              <span class="h-1.5 w-1.5 rounded-full bg-fg-dim animate-bounce"></span>
              <span class="h-1.5 w-1.5 rounded-full bg-fg-dim animate-bounce" style="animation-delay: 0.15s"></span>
              <span class="h-1.5 w-1.5 rounded-full bg-fg-dim animate-bounce" style="animation-delay: 0.3s"></span>
            </span>
            <span>Copilot is thinking…</span>
          </div>
        }
      </div>

      <footer class="px-5 py-3 border-t border-border-light">
        <form (submit)="onSubmit($event)" class="flex items-end gap-2">
          <textarea
            [formControl]="inputCtrl"
            (keydown.enter)="onEnter($event)"
            rows="2"
            placeholder="Ask the copilot…"
            class="flex-1 text-sm bg-surface-2 border border-border-light rounded-[var(--radius-sm)] px-3 py-2 outline-none focus:border-primary/40 resize-none"
            [disabled]="busy()"
          ></textarea>
          <button
            type="submit"
            [disabled]="busy() || !canSubmit()"
            class="shrink-0 inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] bg-primary text-surface text-xs font-semibold px-3 py-2 hover:bg-primary/90 transition disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <span>Send</span>
            <span aria-hidden="true">↗</span>
          </button>
        </form>
      </footer>
    </article>
  `,
})
export class CopilotPanel {
  readonly queryId = input.required<string>();

  readonly #copilot = inject(CopilotService);

  protected readonly suggestedPrompts = SUGGESTED_PROMPTS;
  protected readonly inputCtrl = new FormControl<string>('', { nonNullable: true });
  protected readonly inputSig = signal<string>('');

  protected readonly messages = computed<readonly CopilotMessage[]>(() =>
    this.#copilot.thread(this.queryId()),
  );
  protected readonly busy = computed<boolean>(() => this.#copilot.isBusy(this.queryId()));
  protected readonly canSubmit = computed<boolean>(() => this.inputSig().trim().length > 0);

  constructor() {
    this.inputCtrl.valueChanges.subscribe((v) => this.inputSig.set(v));
  }

  protected onEnter(event: Event): void {
    const e = event as KeyboardEvent;
    if (!e.shiftKey) {
      e.preventDefault();
      this.onSubmit(e);
    }
  }

  protected onSubmit(event?: Event): void {
    // Block the browser's default form submit (which navigates to the
    // page URL and looks like a refresh) regardless of whether the
    // event came from the Send button or the Enter key.
    event?.preventDefault();
    const val = this.inputCtrl.value.trim();
    if (!val || this.busy()) return;
    this.inputCtrl.setValue('');
    void this.#copilot.ask(this.queryId(), val);
  }

  protected sendPrompt(prompt: string): void {
    if (this.busy()) return;
    void this.#copilot.ask(this.queryId(), prompt);
  }

  protected reset(): void {
    this.#copilot.reset(this.queryId());
  }

  protected argsLabel(args: Readonly<Record<string, unknown>> | undefined): string {
    if (!args) return '';
    return Object.entries(args)
      .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
      .join(', ');
  }
}
