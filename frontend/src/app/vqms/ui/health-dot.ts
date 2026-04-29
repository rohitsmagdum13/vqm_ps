import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export type HealthStatus = 'healthy' | 'degraded' | 'down' | 'standby';

const COLORS: Record<HealthStatus, string> = {
  healthy: 'var(--ok)',
  degraded: 'var(--warn)',
  down: 'var(--bad)',
  standby: 'var(--subtle)',
};

@Component({
  selector: 'vq-health-dot',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span
      [class.pulse-dot]="animate()"
      [style.width.px]="8"
      [style.height.px]="8"
      [style.border-radius]="'999px'"
      [style.background]="color()"
      style="display:inline-block;"
    ></span>
  `,
})
export class HealthDot {
  readonly status = input.required<HealthStatus | string>();

  readonly color = computed<string>(
    () => COLORS[(this.status() as HealthStatus) ?? 'standby'] ?? COLORS.standby,
  );
  readonly animate = computed<boolean>(() => {
    const s = this.status();
    return s === 'degraded' || s === 'down';
  });
}
