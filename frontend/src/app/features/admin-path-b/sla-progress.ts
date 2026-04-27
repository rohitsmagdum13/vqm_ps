import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

@Component({
  selector: 'app-sla-progress',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="space-y-1.5">
      <div class="flex items-baseline justify-between text-xs">
        <span class="text-fg-dim">SLA</span>
        <span class="font-mono tabular-nums" [class]="textClass()">
          {{ elapsedHours() }}h / {{ targetHours() }}h
          <span class="text-fg-dim ml-1">({{ pct() }}%)</span>
        </span>
      </div>
      <div class="h-1.5 rounded-full bg-surface-2 overflow-hidden">
        <div class="h-full transition-all" [class]="barClass()" [style.width.%]="clampedPct()"></div>
      </div>
      <div class="flex items-center justify-between text-[10px] text-fg-dim">
        <span>{{ statusLabel() }}</span>
        <span>{{ remainingLabel() }}</span>
      </div>
    </div>
  `,
})
export class SlaProgress {
  readonly elapsedHours = input.required<number>();
  readonly targetHours = input.required<number>();

  protected readonly pct = computed<number>(() =>
    Math.round((this.elapsedHours() / this.targetHours()) * 100),
  );

  protected readonly clampedPct = computed<number>(() => Math.min(this.pct(), 100));

  protected readonly textClass = computed<string>(() => {
    const p = this.pct();
    if (p >= 95) return 'text-error';
    if (p >= 70) return 'text-warn';
    return 'text-success';
  });

  protected readonly barClass = computed<string>(() => {
    const p = this.pct();
    if (p >= 95) return 'bg-error';
    if (p >= 70) return 'bg-warn';
    return 'bg-success';
  });

  protected readonly statusLabel = computed<string>(() => {
    const p = this.pct();
    if (p >= 100) return 'Breached';
    if (p >= 95) return 'L2 escalation';
    if (p >= 85) return 'L1 escalation';
    if (p >= 70) return 'Warning';
    return 'On track';
  });

  protected readonly remainingLabel = computed<string>(() => {
    const remaining = this.targetHours() - this.elapsedHours();
    if (remaining <= 0) return `${(-remaining).toFixed(1)}h overdue`;
    return `${remaining.toFixed(1)}h remaining`;
  });
}
