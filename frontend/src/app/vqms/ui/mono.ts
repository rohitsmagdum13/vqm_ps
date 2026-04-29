import { ChangeDetectionStrategy, Component, input } from '@angular/core';

@Component({
  selector: 'vq-mono',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span
      class="mono"
      [class]="cssClass()"
      [style.color]="color() || 'var(--ink-2)'"
      [style.font-size.px]="size()"
      [style.font-weight]="weight()"
    >
      <ng-content />
    </span>
  `,
})
export class Mono {
  readonly size = input<number>(12);
  readonly weight = input<number | string>(400);
  readonly color = input<string>('');
  readonly cssClass = input<string>('');
}
