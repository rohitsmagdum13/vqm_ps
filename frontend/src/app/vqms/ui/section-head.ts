import { ChangeDetectionStrategy, Component, input } from '@angular/core';

@Component({
  selector: 'vq-section-head',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="flex items-end justify-between mb-3">
      <div>
        <div class="ink" style="font-size: 14px; font-weight: 600;">{{ title() }}</div>
        @if (desc()) {
          <div class="muted mt-0.5" style="font-size: 12px;">{{ desc() }}</div>
        }
      </div>
      <ng-content />
    </div>
  `,
})
export class SectionHead {
  readonly title = input.required<string>();
  readonly desc = input<string>('');
}
