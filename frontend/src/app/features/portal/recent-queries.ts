import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { BadgeComponent } from '../../shared/ui/badge/badge';
import { priorityTone, statusTone } from '../../shared/ui/badge/badge-tones';
import type { Query } from '../../shared/models/query';

@Component({
  selector: 'app-portal-recent-queries',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [BadgeComponent],
  template: `
    <div class="flex flex-col gap-2">
      @for (q of queries(); track q.id) {
        <button
          type="button"
          (click)="open.emit(q.id)"
          class="grid grid-cols-[110px_1fr_auto_auto_auto] items-center gap-3 text-left rounded-[var(--radius-sm)] bg-surface border border-border-light px-3 py-2 hover:border-primary hover:shadow-sm transition"
        >
          <span class="text-[11px] font-mono text-fg-dim truncate">{{ q.id }}</span>
          <span class="text-sm text-fg truncate">{{ q.subj }}</span>
          <ui-badge [tone]="statusTone(q.status)">{{ q.status }}</ui-badge>
          <ui-badge [tone]="priorityTone(q.pri)">{{ q.pri }}</ui-badge>
          <span class="text-[11px] text-fg-dim hidden sm:inline">{{ q.submitted }}</span>
        </button>
      } @empty {
        <div class="text-sm text-fg-dim italic">No queries yet.</div>
      }
    </div>
  `,
})
export class PortalRecentQueries {
  readonly queries = input.required<readonly Query[]>();
  readonly open = output<string>();

  protected readonly statusTone = statusTone;
  protected readonly priorityTone = priorityTone;
}
