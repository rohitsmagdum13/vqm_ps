import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import type { ConfidenceBreakdown } from '../../shared/models/triage';

interface DimensionRow {
  readonly label: string;
  readonly key: keyof ConfidenceBreakdown;
  readonly score: number;
  readonly isWeakest: boolean;
}

@Component({
  selector: 'app-confidence-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <article class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-5 space-y-4">
      <header class="flex items-start justify-between gap-3">
        <div>
          <h2 class="text-sm font-semibold text-fg">Confidence breakdown</h2>
          <p class="mt-0.5 text-[11px] text-fg-dim">
            Below the 0.85 threshold ⇒ Path C (human review required)
          </p>
        </div>
        <div class="text-right">
          <div class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">Overall</div>
          <div class="text-2xl font-semibold tabular-nums" [class]="overallColorClass()">
            {{ overall().toFixed(2) }}
          </div>
        </div>
      </header>

      <ul class="space-y-2">
        @for (row of rows(); track row.key) {
          <li>
            <div class="flex items-center justify-between text-xs mb-1">
              <span class="text-fg flex items-center gap-2">
                {{ row.label }}
                @if (row.isWeakest) {
                  <span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-error/15 text-error text-[10px] font-semibold">
                    weakest
                  </span>
                }
              </span>
              <span class="font-mono tabular-nums" [class]="row.score < 0.6 ? 'text-error' : row.score < 0.75 ? 'text-warn' : 'text-success'">
                {{ row.score.toFixed(2) }}
              </span>
            </div>
            <div class="h-2 rounded-full bg-surface-2 overflow-hidden">
              <div
                class="h-full transition-all"
                [class]="row.score < 0.6 ? 'bg-error' : row.score < 0.75 ? 'bg-warn' : 'bg-success'"
                [style.width.%]="row.score * 100"
              ></div>
            </div>
          </li>
        }
      </ul>

      @if (reasons().length > 0) {
        <section class="pt-3 border-t border-border-light">
          <h3 class="text-[11px] font-semibold uppercase tracking-wider text-fg-dim mb-2">
            Why the AI was uncertain
          </h3>
          <ul class="space-y-1.5 text-xs text-fg-dim">
            @for (reason of reasons(); track reason) {
              <li class="flex gap-2">
                <span class="text-error shrink-0" aria-hidden="true">⚠</span>
                <span>{{ reason }}</span>
              </li>
            }
          </ul>
        </section>
      }
    </article>
  `,
})
export class ConfidenceCard {
  readonly breakdown = input.required<ConfidenceBreakdown>();
  readonly overall = input.required<number>();
  readonly reasons = input.required<readonly string[]>();

  protected readonly rows = computed<readonly DimensionRow[]>(() => {
    const b = this.breakdown();
    // These dimension keys match the backend triage node output —
    // src/orchestration/nodes/triage.py::_build_confidence_breakdown.
    const dims: ReadonlyArray<{ label: string; key: keyof ConfidenceBreakdown }> = [
      { label: 'Intent classification', key: 'intent_classification' },
      { label: 'Entity extraction', key: 'entity_extraction' },
      { label: 'Single issue detection', key: 'single_issue_detection' },
    ];
    const minScore = Math.min(...dims.map((d) => b[d.key] ?? 0));
    return dims.map((d) => ({
      label: d.label,
      key: d.key,
      score: b[d.key] ?? 0,
      isWeakest: (b[d.key] ?? 0) === minScore,
    }));
  });

  protected readonly overallColorClass = computed<string>(() => {
    const c = this.overall();
    if (c < 0.6) return 'text-error';
    if (c < 0.75) return 'text-warn';
    return 'text-success';
  });
}
