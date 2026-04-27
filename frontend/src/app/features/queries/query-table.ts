import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { BadgeComponent } from '../../shared/ui/badge/badge';
import { priorityTone, statusTone } from '../../shared/ui/badge/badge-tones';
import type { Query } from '../../shared/models/query';

@Component({
  selector: 'app-query-table',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [BadgeComponent],
  template: `
    <div
      class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm overflow-hidden"
    >
      <div class="overflow-x-auto">
        <table class="w-full border-collapse text-sm min-w-[900px]">
          <thead class="bg-surface-2 text-fg-dim">
            <tr>
              <th class="px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">Query ID</th>
              <th class="px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">Subject</th>
              @if (showVendor()) {
                <th class="px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">Vendor</th>
              }
              <th class="px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">Type</th>
              <th class="px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">Priority</th>
              <th class="px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">Status</th>
              <th class="px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">Source</th>
              <th class="px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">Submitted</th>
              <th class="px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">SLA</th>
              <th class="px-4 py-2 text-right text-[10px] font-mono tracking-wider uppercase">Actions</th>
            </tr>
          </thead>
          <tbody>
            @for (q of rows(); track q.id) {
              <tr
                (click)="open.emit(q.id)"
                class="border-t border-border-light hover:bg-surface-2 cursor-pointer transition"
              >
                <td class="px-4 py-3 font-mono text-[11px] text-fg-dim whitespace-nowrap">{{ q.id }}</td>
                <td class="px-4 py-3 text-fg max-w-xs truncate" [title]="q.subj">{{ q.subj }}</td>
                @if (showVendor()) {
                  <td class="px-4 py-3 text-fg-dim text-xs font-mono whitespace-nowrap">
                    {{ q.vendor ?? '—' }}
                  </td>
                }
                <td class="px-4 py-3 text-fg-dim text-xs whitespace-nowrap">{{ q.type }}</td>
                <td class="px-4 py-3"><ui-badge [tone]="priorityTone(q.pri)">{{ q.pri }}</ui-badge></td>
                <td class="px-4 py-3"><ui-badge [tone]="statusTone(q.status)">{{ q.status }}</ui-badge></td>
                <td class="px-4 py-3 text-fg-dim text-xs whitespace-nowrap">{{ q.agent }}</td>
                <td class="px-4 py-3 text-fg-dim text-xs whitespace-nowrap">{{ q.submitted }}</td>
                <td
                  class="px-4 py-3 font-mono text-xs whitespace-nowrap"
                  [class]="slaClass(q.slaCls)"
                >{{ q.sla }}</td>
                <td class="px-4 py-3 text-right">
                  <button
                    type="button"
                    (click)="$event.stopPropagation(); open.emit(q.id)"
                    class="text-xs text-primary hover:underline whitespace-nowrap"
                  >Details →</button>
                </td>
              </tr>
            } @empty {
              <tr>
                <td [attr.colspan]="colSpan()" class="px-4 py-8 text-center text-fg-dim text-sm">
                  No queries match the current filters.
                </td>
              </tr>
            }
          </tbody>
        </table>
      </div>
    </div>
  `,
})
export class QueryTable {
  readonly rows = input.required<readonly Query[]>();
  /** Show the Vendor column. Pass true for admin views. */
  readonly showVendor = input<boolean>(false);
  readonly open = output<string>();

  protected readonly statusTone = statusTone;
  protected readonly priorityTone = priorityTone;

  protected slaClass(cls: 'sla-ok' | 'sla-brch'): string {
    return cls === 'sla-brch' ? 'text-error' : 'text-success';
  }

  /** Total visible columns — drives the empty-state colspan. */
  protected colSpan(): number {
    // Query ID, Subject, [Vendor], Type, Priority, Status, Source, Submitted, SLA, Actions
    return this.showVendor() ? 10 : 9;
  }
}
