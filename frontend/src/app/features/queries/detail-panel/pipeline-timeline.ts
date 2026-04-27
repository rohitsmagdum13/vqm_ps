import {
  ChangeDetectionStrategy,
  Component,
  computed,
  input,
  signal,
} from '@angular/core';
import { DatePipe } from '@angular/common';
import type { TimelineEvent } from '../../../shared/models/timeline';

/**
 * Live per-query pipeline timeline.
 *
 * Renders one entry per `audit.action_log` row returned by GET
 * /queries/:id.trail — the LangGraph nodes, LLM sub-calls, intake,
 * admin actions and closure milestones — with a status badge
 * (✓ / ✗ / …), a humanised step name, duration, and an expandable
 * details payload. Polling is owned by the parent component; this one
 * is purely presentational.
 */

interface RenderedRow {
  readonly id: number;
  readonly icon: string;
  readonly toneClass: string;
  readonly title: string;
  readonly subtitle: string;
  readonly durationLabel: string | null;
  readonly timestamp: string;
  readonly inProgress: boolean;
  readonly raw: TimelineEvent;
}

const STEP_LABELS: Record<string, string> = {
  intake: 'Query received',
  context_loading: 'Vendor context loaded',
  query_analysis: 'AI analysis (LLM #1)',
  confidence_check: 'Confidence check',
  routing: 'Routed to team',
  kb_search: 'Knowledge base searched',
  path_decision: 'Path selected',
  resolution: 'Resolution drafted',
  acknowledgment: 'Acknowledgment drafted',
  resolution_from_notes: 'Resolution drafted from notes',
  quality_gate: 'Quality gate',
  delivery: 'Delivery',
  llm_call: 'LLM call',
  triage: 'Triage',
  draft_approval: 'Admin draft approval',
  closure: 'Closure',
};

function humanise(stepName: string): string {
  return STEP_LABELS[stepName] ?? stepName.replace(/_/g, ' ');
}

function actionLabel(stepName: string, action: string): string {
  if (!action || action === 'execute') return '';
  if (stepName === 'llm_call') return action.split('.').pop() ?? action;
  return action.replace(/_/g, ' ');
}

function statusToTone(status: string): { icon: string; tone: string } {
  switch (status) {
    case 'success':
      return { icon: '✓', tone: 'bg-success/15 text-success border-success/30' };
    case 'failed':
      return { icon: '✗', tone: 'bg-error/15 text-error border-error/30' };
    case 'skipped':
      return {
        icon: '−',
        tone: 'bg-surface-2 text-fg-dim border-border-light',
      };
    default:
      return {
        icon: '…',
        tone: 'bg-primary/15 text-primary border-primary/30',
      };
  }
}

function formatDuration(ms: number | null | undefined): string | null {
  if (ms == null) return null;
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

@Component({
  selector: 'app-pipeline-timeline',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe],
  template: `
    <section
      class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-5"
    >
      <header class="flex items-center justify-between gap-3 mb-4">
        <div>
          <h2 class="text-sm font-semibold text-fg">Pipeline timeline</h2>
          <p class="text-[11px] text-fg-dim mt-0.5">
            Real-time per-step execution trail
            @if (polling()) {
              <span class="inline-flex items-center gap-1 ml-2 text-primary">
                <span class="inline-block h-1.5 w-1.5 rounded-full bg-primary animate-pulse"></span>
                live
              </span>
            }
          </p>
        </div>
        <span class="text-[10px] font-mono text-fg-dim">
          {{ rows().length }} step{{ rows().length === 1 ? '' : 's' }}
        </span>
      </header>

      @if (rows().length === 0) {
        <div class="text-center text-xs text-fg-dim py-8">
          No timeline events yet.
          @if (polling()) {
            <span> Waiting for the pipeline to start…</span>
          }
        </div>
      } @else {
        <ol class="space-y-0">
          @for (row of rows(); track row.id; let last = $last) {
            <li class="relative flex gap-3 pb-4">
              @if (!last) {
                <span
                  class="absolute left-[12px] top-7 bottom-0 w-px bg-border-light"
                  aria-hidden="true"
                ></span>
              }
              <span
                class="relative z-10 mt-0.5 h-6 w-6 shrink-0 rounded-full grid place-items-center text-[11px] font-mono border"
                [class]="row.toneClass"
                [class.animate-pulse]="row.inProgress"
              >{{ row.icon }}</span>
              <div class="min-w-0 flex-1">
                <div class="flex items-baseline justify-between gap-2 flex-wrap">
                  <div class="min-w-0">
                    <span class="text-sm text-fg font-medium">{{ row.title }}</span>
                    @if (row.subtitle) {
                      <span class="ml-2 text-[11px] font-mono text-fg-dim">
                        · {{ row.subtitle }}
                      </span>
                    }
                  </div>
                  <div class="flex items-center gap-2 text-[10px] font-mono text-fg-dim shrink-0">
                    @if (row.durationLabel) {
                      <span>{{ row.durationLabel }}</span>
                    }
                    <span>{{ row.timestamp | date: 'MMM d, HH:mm:ss' }}</span>
                  </div>
                </div>
                @if (showDetails() && hasDetails(row.raw)) {
                  <details class="mt-1.5">
                    <summary
                      class="cursor-pointer text-[11px] text-primary hover:underline list-none select-none"
                    >Details</summary>
                    <pre
                      class="mt-1.5 text-[10px] leading-relaxed text-fg-dim bg-surface-2 border border-border-light rounded-[var(--radius-sm)] p-2 overflow-x-auto whitespace-pre-wrap"
                    >{{ formatDetails(row.raw) }}</pre>
                  </details>
                }
              </div>
            </li>
          }
        </ol>
      }
    </section>
  `,
})
export class PipelineTimeline {
  readonly events = input.required<readonly TimelineEvent[]>();
  /** Set true while the parent is polling so we render the "live" badge. */
  readonly polling = input<boolean>(false);
  /** Admins see expandable details with model/tokens/cost. */
  readonly showDetails = input<boolean>(true);

  protected readonly rows = computed<readonly RenderedRow[]>(() => {
    const list = this.events();
    if (list.length === 0) return [];

    // Mark only the latest in_progress row as animating, so the timeline
    // always shows ONE active dot at most. Backend writes a row per node
    // boundary so most events are terminal — this guard is defensive.
    const lastIdx = list.length - 1;
    return list.map((event, i) => {
      const status = (event.status ?? 'success').toLowerCase();
      const tone = statusToTone(status);
      const action = actionLabel(event.step_name, event.action ?? '');
      return {
        id: event.id,
        icon: tone.icon,
        toneClass: tone.tone,
        title: humanise(event.step_name),
        subtitle: action,
        durationLabel: formatDuration(event.duration_ms),
        timestamp: event.created_at,
        inProgress:
          status !== 'success' &&
          status !== 'failed' &&
          status !== 'skipped' &&
          i === lastIdx,
        raw: event,
      };
    });
  });

  // Expose a hint to *ngIf so empty `details` blocks don't render an
  // empty <details> stub.
  protected hasDetails(event: TimelineEvent): boolean {
    return Object.keys(event.details ?? {}).length > 0;
  }

  protected formatDetails(event: TimelineEvent): string {
    return JSON.stringify(event.details ?? {}, null, 2);
  }
}
