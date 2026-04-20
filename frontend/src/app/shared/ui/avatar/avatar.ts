import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export type AvatarSize = 'sm' | 'md' | 'lg';

@Component({
  selector: 'ui-avatar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span
      class="inline-flex items-center justify-center rounded-full bg-primary text-surface font-mono font-medium select-none"
      [class]="sizeClass()"
      [title]="title()"
    >{{ initials() }}</span>
  `,
})
export class AvatarComponent {
  readonly initials = input.required<string>();
  readonly title = input<string>('');
  readonly size = input<AvatarSize>('md');

  protected readonly sizeClass = computed(() => {
    const map: Record<AvatarSize, string> = {
      sm: 'h-7 w-7 text-[11px]',
      md: 'h-9 w-9 text-sm',
      lg: 'h-12 w-12 text-base',
    };
    return map[this.size()];
  });
}
