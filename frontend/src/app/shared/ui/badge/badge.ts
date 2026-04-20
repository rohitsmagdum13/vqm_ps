import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export type BadgeTone = 'info' | 'success' | 'warn' | 'error' | 'neutral' | 'primary';

@Component({
  selector: 'ui-badge',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span
      class="inline-flex items-center gap-1 rounded-full px-2 py-[2px] font-mono text-[9.5px] tracking-wider uppercase border"
      [class]="toneClass()"
    >
      <ng-content />
    </span>
  `,
})
export class BadgeComponent {
  readonly tone = input<BadgeTone>('neutral');

  protected readonly toneClass = computed(() => {
    const map: Record<BadgeTone, string> = {
      info: 'bg-info/10 text-info border-info/20',
      success: 'bg-success/10 text-success border-success/20',
      warn: 'bg-warn/10 text-warn border-warn/20',
      error: 'bg-error/10 text-error border-error/20',
      neutral: 'bg-surface-2 text-fg-dim border-border-light',
      primary: 'bg-primary/10 text-primary border-primary/20',
    };
    return map[this.tone()];
  });
}
