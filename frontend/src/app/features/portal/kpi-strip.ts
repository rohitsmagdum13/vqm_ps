import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { KpiCardComponent } from '../../shared/ui/kpi-card/kpi-card';

@Component({
  selector: 'app-portal-kpi-strip',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [KpiCardComponent],
  template: `
    <div class="grid grid-cols-1 md:grid-cols-3 gap-8">
      <ui-kpi-card
        label="Open Queries"
        [value]="openCount()"
        accent="info"
        trend="flat"
        trendText="2 near SLA"
        subtext="this month"
        [spark]="openSpark"
        sparkTone="info"
        [clickable]="true"
        (select)="openQueries.emit()"
      />
      <ui-kpi-card
        label="Resolved"
        [value]="resolvedCount()"
        accent="success"
        trend="up"
        trendText="↑ 3 vs last month"
        subtext="avg 3.8h"
        [spark]="resolvedSpark"
        sparkTone="success"
        [clickable]="true"
        (select)="openQueries.emit()"
      />
      <ui-kpi-card
        label="Avg Response"
        value="2.4h"
        accent="warn"
        trend="up"
        trendText="↓ 18% faster"
        subtext="SLA target 4h"
        [spark]="responseSpark"
        sparkTone="warn"
      />
    </div>
  `,
})
export class PortalKpiStrip {
  readonly openCount = input.required<number>();
  readonly resolvedCount = input.required<number>();

  readonly openQueries = output<void>();

  protected readonly openSpark: readonly number[] = [4, 5, 4, 6, 5, 7, 6, 7, 6, 6];
  protected readonly resolvedSpark: readonly number[] = [8, 9, 10, 11, 10, 12, 12, 13, 14, 14];
  protected readonly responseSpark: readonly number[] = [3.8, 3.5, 4.2, 3.9, 3.6, 3.2, 2.8, 2.6, 2.5, 2.4];
}
