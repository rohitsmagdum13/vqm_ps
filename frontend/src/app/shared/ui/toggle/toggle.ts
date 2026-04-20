import { ChangeDetectionStrategy, Component, computed, input, model } from '@angular/core';

@Component({
  selector: 'ui-toggle',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <button
      type="button"
      role="switch"
      [attr.aria-checked]="checked()"
      [attr.aria-label]="label()"
      [disabled]="disabled()"
      (click)="toggle()"
      class="relative inline-flex h-5 w-9 items-center rounded-full transition border"
      [class]="trackClass()"
    >
      <span
        class="inline-block h-3.5 w-3.5 rounded-full bg-surface shadow transition"
        [class]="knobClass()"
      ></span>
    </button>
  `,
})
export class ToggleComponent {
  readonly checked = model<boolean>(false);
  readonly disabled = input<boolean>(false);
  readonly label = input<string>('');

  protected toggle(): void {
    if (this.disabled()) return;
    this.checked.update((v) => !v);
  }

  protected readonly trackClass = computed(() =>
    this.checked()
      ? 'bg-primary border-primary'
      : 'bg-surface-2 border-border-light',
  );

  protected readonly knobClass = computed(() =>
    this.checked() ? 'translate-x-[18px]' : 'translate-x-[3px]',
  );
}
