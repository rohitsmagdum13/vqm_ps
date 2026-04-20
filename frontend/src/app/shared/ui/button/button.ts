import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export type ButtonVariant = 'primary' | 'ghost' | 'danger' | 'accent';
export type ButtonSize = 'sm' | 'md';

@Component({
  selector: 'ui-button',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <button
      [type]="type()"
      [disabled]="disabled()"
      [class]="cls()"
    >
      <ng-content />
    </button>
  `,
})
export class ButtonComponent {
  readonly variant = input<ButtonVariant>('primary');
  readonly size = input<ButtonSize>('md');
  readonly type = input<'button' | 'submit' | 'reset'>('button');
  readonly disabled = input<boolean>(false);

  protected readonly cls = computed(() => {
    const base =
      'inline-flex items-center justify-center gap-2 font-medium rounded-[var(--radius-sm)] transition disabled:opacity-60 disabled:cursor-not-allowed whitespace-nowrap';

    const sizeMap: Record<ButtonSize, string> = {
      sm: 'text-xs px-3 py-1.5',
      md: 'text-sm px-4 py-2',
    };

    const variantMap: Record<ButtonVariant, string> = {
      primary: 'bg-primary text-surface hover:bg-secondary shadow-sm',
      accent: 'bg-accent text-secondary hover:brightness-95',
      ghost:
        'bg-surface text-fg-dim hover:text-fg border border-border-light hover:border-border-dark',
      danger: 'bg-error text-surface hover:brightness-95 shadow-sm',
    };

    return `${base} ${sizeMap[this.size()]} ${variantMap[this.variant()]}`;
  });
}
