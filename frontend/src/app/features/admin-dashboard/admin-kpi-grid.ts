import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import type { AdminKpi } from './admin-dashboard.data';

@Component({
  selector: 'app-admin-kpi-grid',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-8">
      @for (k of kpis(); track k.lbl) {
        <div
          class="relative rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-4 overflow-hidden"
        >
          <span class="absolute left-0 top-0 bottom-0 w-[3px]" [class]="accentBg(k.accent)"></span>
          <div class="flex items-start justify-between gap-3">
            <div class="text-[10px] font-mono tracking-wider uppercase text-fg-dim">{{ k.lbl }}</div>
            <div
              class="h-7 w-7 shrink-0 rounded-full flex items-center justify-center text-base"
              [class]="iconBg(k.accent)"
            >
              {{ k.ico }}
            </div>
          </div>
          <div class="mt-2 text-2xl font-mono font-semibold text-fg">{{ k.v }}</div>
          <div class="mt-1 text-[11px] font-mono" [class]="toneClass(k.tone)">{{ k.d }}</div>
        </div>
      }
    </div>
  `,
})
export class AdminKpiGrid {
  readonly kpis = input.required<readonly AdminKpi[]>();

  protected accentBg(accent: AdminKpi['accent']): string {
    const map: Record<AdminKpi['accent'], string> = {
      primary: 'bg-primary',
      success: 'bg-success',
      warn: 'bg-warn',
      error: 'bg-error',
    };
    return map[accent];
  }

  protected iconBg(accent: AdminKpi['accent']): string {
    const map: Record<AdminKpi['accent'], string> = {
      primary: 'bg-primary/10 text-primary',
      success: 'bg-success/10 text-success',
      warn: 'bg-warn/10 text-warn',
      error: 'bg-error/10 text-error',
    };
    return map[accent];
  }

  protected toneClass(tone: AdminKpi['tone']): string {
    switch (tone) {
      case 'tg':
        return 'text-success';
      case 'tr':
        return 'text-error';
      case 'ta':
        return 'text-warn';
    }
  }
}
