import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

@Component({
  selector: 'app-wizard-success',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="flex flex-col items-center text-center space-y-5 py-6">
      <div
        class="h-16 w-16 rounded-full bg-success/10 border-2 border-success flex items-center justify-center"
      >
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path
            d="M5 12l4 4 10-10"
            stroke="var(--color-success)"
            stroke-width="2.4"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </div>

      <div class="space-y-1">
        <h2 class="text-lg font-semibold text-fg">Query submitted</h2>
        <p class="text-sm text-fg-dim">Your query has been logged and routed to the AI pipeline.</p>
      </div>

      <div
        class="rounded-[var(--radius-sm)] bg-primary/5 border border-primary/20 px-4 py-2 font-mono text-sm text-primary"
      >
        {{ queryId() }}
      </div>

      <div class="w-full rounded-[var(--radius-md)] bg-surface-2 border border-border-light p-4 text-left space-y-2">
        <div class="text-[10px] font-mono tracking-wider uppercase text-fg-dim">What happens next</div>
        <ol class="space-y-2 text-sm text-fg">
          <li class="flex gap-2">
            <span class="text-success">✓</span>
            <span>AI classifies priority and category</span>
          </li>
          <li class="flex gap-2">
            <span class="text-success">✓</span>
            <span>Routed to the resolution queue</span>
          </li>
          <li class="flex gap-2">
            <span class="text-fg-dim">•</span>
            <span class="text-fg-dim">AI drafts a response from the knowledge base</span>
          </li>
          <li class="flex gap-2">
            <span class="text-fg-dim">•</span>
            <span class="text-fg-dim">Human reviewer approves &amp; sends</span>
          </li>
        </ol>
      </div>

      <div class="flex flex-wrap gap-2 justify-center">
        <button
          type="button"
          (click)="track.emit()"
          class="inline-flex items-center gap-1 rounded-[var(--radius-sm)] bg-primary text-surface text-xs font-medium px-4 py-2 hover:bg-secondary transition"
        >
          Track {{ queryId() }} →
        </button>
        <button
          type="button"
          (click)="newOne.emit()"
          class="inline-flex items-center gap-1 rounded-[var(--radius-sm)] bg-surface border border-border-light text-xs font-medium text-fg px-4 py-2 hover:bg-surface-2 transition"
        >
          Raise another
        </button>
        <button
          type="button"
          (click)="done.emit()"
          class="inline-flex items-center gap-1 rounded-[var(--radius-sm)] bg-surface border border-border-light text-xs font-medium text-fg-dim px-4 py-2 hover:bg-surface-2 transition"
        >
          Back to portal
        </button>
      </div>
    </div>
  `,
})
export class WizardSuccess {
  readonly queryId = input.required<string>();
  readonly track = output<void>();
  readonly newOne = output<void>();
  readonly done = output<void>();
}
