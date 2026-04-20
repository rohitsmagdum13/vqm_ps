import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export type SpinnerSize = 'sm' | 'md' | 'lg';

@Component({
  selector: 'ui-spinner',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span
      class="inline-block rounded-full border-2 border-border-light border-t-primary"
      [class]="sizeClass()"
      [style.animation]="'spin 0.8s linear infinite'"
      role="status"
      [attr.aria-label]="label()"
    ></span>
  `,
})
export class SpinnerComponent {
  readonly size = input<SpinnerSize>('md');
  readonly label = input<string>('Loading');

  protected readonly sizeClass = computed(() => {
    const map: Record<SpinnerSize, string> = {
      sm: 'h-4 w-4 border-2',
      md: 'h-6 w-6 border-[3px]',
      lg: 'h-10 w-10 border-4',
    };
    return map[this.size()];
  });
}
