import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { Icon } from '../../ui/icon';
import { Mono } from '../../ui/mono';
import { fmtMailTime } from '../../data/mail';
import type { MailAiDraft } from '../../data/mail';

@Component({
  selector: 'vq-mail-ai-draft-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Icon, Mono],
  template: `
    <div class="px-6 pt-5">
      <div
        class="panel fade-up"
        [style.border-radius.px]="4"
        [style.border-color]="
          passed()
            ? 'color-mix(in oklch, var(--accent) 35%, var(--line-strong))'
            : 'var(--line-strong)'
        "
        style="background: linear-gradient(180deg, var(--accent-soft) 0%, var(--panel) 30%);"
      >
        <div class="px-5 py-3 border-b hairline flex items-center gap-3">
          <vq-icon name="sparkles" [size]="14" cssClass="text-accent" />
          <span class="ink" style="font-size:12.5px; font-weight:600;">
            AI‑suggested {{ ai().draft_type === 'RESOLUTION' ? 'resolution' : 'acknowledgment' }}
          </span>
          <vq-mono cssClass="muted" [size]="10.5">{{ ai().draft_id }}</vq-mono>
          <span class="flex-1"></span>
          <span
            class="chip"
            [style.color]="confColor()"
            [style.font-weight]="600"
          >
            confidence
            <vq-mono cssClass="ml-1" [size]="11">{{ ai().confidence.toFixed(2) }}</vq-mono>
          </span>
          <span
            class="chip"
            [style.color]="passed() ? 'var(--ok)' : 'var(--bad)'"
            [style.background]="
              passed()
                ? 'color-mix(in oklch, var(--ok) 10%, var(--panel))'
                : 'color-mix(in oklch, var(--bad) 10%, var(--panel))'
            "
          >
            <vq-icon [name]="passed() ? 'shield-check' : 'shield-alert'" [size]="10" />
            QG {{ ai().quality_gate.checks_passed }}/{{ totalChecks() }}
          </span>
        </div>

        <div class="px-5 py-4">
          <pre
            class="ink-2"
            style="font-family: inherit; white-space: pre-wrap; font-size:12.5px; line-height:1.6; margin:0;"
            >{{ ai().body_text }}</pre>

          @if (ai().sources.length > 0) {
            <div class="mt-3 pt-3 border-t hairline">
              <div
                class="muted uppercase tracking-wider mb-1.5"
                style="font-size:10px; font-weight:600;"
              >
                Sources
              </div>
              <div class="flex flex-wrap gap-1.5">
                @for (s of ai().sources; track s.kb_id) {
                  <span class="chip" style="font-size:10.5px;">
                    <vq-mono [size]="10">{{ s.kb_id }}</vq-mono> · {{ s.title }} · cosine
                    <vq-mono [size]="10">{{ s.cosine }}</vq-mono>
                  </span>
                }
              </div>
            </div>
          }
        </div>

        <div class="px-5 py-3 border-t hairline flex items-center gap-2">
          <button class="btn btn-accent" (click)="use.emit()">
            <vq-icon name="check" [size]="13" /> Use this
          </button>
          <button class="btn" (click)="use.emit()">
            <vq-icon name="edit-3" [size]="13" /> Edit
          </button>
          <button class="btn">
            <vq-icon name="refresh-cw" [size]="13" /> Regenerate
          </button>
          <button class="btn">
            <vq-icon name="x" [size]="13" /> Reject
          </button>
          <span class="flex-1"></span>
          <vq-mono cssClass="muted" [size]="10">
            generated {{ generated() }} · Amazon Bedrock
          </vq-mono>
        </div>
      </div>
    </div>
  `,
})
export class AiDraftCard {
  readonly ai = input.required<MailAiDraft>();
  readonly use = output<void>();

  protected readonly passed = computed<boolean>(() => this.ai().quality_gate.passed);
  protected readonly totalChecks = computed<number>(() => {
    const qg = this.ai().quality_gate;
    return qg.checks_passed + qg.checks_failed;
  });
  protected readonly confColor = computed<string>(() => {
    const c = this.ai().confidence;
    return c >= 0.85 ? 'var(--ok)' : c >= 0.6 ? 'var(--warn)' : 'var(--bad)';
  });
  protected readonly generated = computed<string>(() => fmtMailTime(this.ai().generated_at));
}
