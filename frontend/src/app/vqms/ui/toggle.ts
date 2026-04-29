import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

@Component({
  selector: 'vq-toggle',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <button
      type="button"
      [disabled]="disabled()"
      (click)="toggled.emit(!on())"
      [style.width.px]="32"
      [style.height.px]="18"
      [style.border-radius]="'999px'"
      [style.background]="on() ? 'var(--accent)' : 'var(--line-strong)'"
      [style.opacity]="disabled() ? 0.5 : 1"
      [style.cursor]="disabled() ? 'not-allowed' : 'pointer'"
      style="border: none; padding: 2px; position: relative; transition: background 120ms ease;"
    >
      <span
        [style.transform]="on() ? 'translateX(14px)' : 'translateX(0)'"
        style="display:block; width:14px; height:14px; border-radius:999px; background:white; transition: transform 120ms ease;"
      ></span>
    </button>
  `,
})
export class Toggle {
  readonly on = input.required<boolean>();
  readonly disabled = input<boolean>(false);
  readonly toggled = output<boolean>();
}
