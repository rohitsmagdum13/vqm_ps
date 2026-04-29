import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { Icon } from './icon';

@Component({
  selector: 'vq-empty',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Icon],
  template: `
    <div class="flex flex-col items-center justify-center py-16 text-center fade-up">
      <div
        [style.width.px]="48"
        [style.height.px]="48"
        [style.border-radius]="'999px'"
        [style.background]="'var(--bg)'"
        style="display:flex; align-items:center; justify-content:center;"
      >
        <vq-icon [name]="icon()" [size]="20" cssClass="subtle" />
      </div>
      <div class="ink mt-3" style="font-size: 14px; font-weight: 500;">{{ title() }}</div>
      @if (desc()) {
        <div class="muted mt-1" style="font-size: 12px; max-width: 320px;">{{ desc() }}</div>
      }
    </div>
  `,
})
export class Empty {
  readonly icon = input<string>('inbox');
  readonly title = input.required<string>();
  readonly desc = input<string>('');
}
