import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import type { AdminAlert } from './admin-dashboard.data';

@Component({
  selector: 'app-admin-alerts',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <ul class="space-y-2">
      @for (a of alerts(); track a.ttl) {
        <li
          class="flex items-start gap-3 rounded-[var(--radius-md)] border px-3 py-2.5 text-sm"
          [class]="rowClass(a.severity)"
        >
          <span class="text-base leading-5" aria-hidden="true">{{ a.ico }}</span>
          <div class="min-w-0">
            <div class="font-medium text-fg">{{ a.ttl }}</div>
            <div class="mt-0.5 text-[11px] text-fg-dim">{{ a.sub }}</div>
          </div>
        </li>
      }
    </ul>
  `,
})
export class AdminAlerts {
  readonly alerts = input.required<readonly AdminAlert[]>();

  protected rowClass(severity: AdminAlert['severity']): string {
    const map: Record<AdminAlert['severity'], string> = {
      error: 'bg-error/5 border-error/20',
      warn: 'bg-warn/5 border-warn/20',
      info: 'bg-surface-2 border-border-light',
    };
    return map[severity];
  }
}
