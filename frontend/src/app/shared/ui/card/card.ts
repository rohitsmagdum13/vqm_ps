import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export type CardAccent = 'primary' | 'success' | 'warn' | 'info' | 'error' | 'none';

@Component({
  selector: 'ui-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section
      class="relative overflow-hidden rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm transition"
      [class.hover:shadow-md]="hover()"
      [class.hover:-translate-y-0.5]="hover()"
      [class.cursor-pointer]="hover()"
      [class.p-5]="padded()"
    >
      @if (accent() !== 'none') {
        <span class="absolute left-0 top-0 bottom-0 w-[3px]" [class]="accentClass()"></span>
      }
      <ng-content />
    </section>
  `,
})
export class CardComponent {
  readonly accent = input<CardAccent>('none');
  readonly hover = input<boolean>(false);
  readonly padded = input<boolean>(true);

  protected readonly accentClass = computed(() => {
    const map: Record<Exclude<CardAccent, 'none'>, string> = {
      primary: 'bg-primary',
      success: 'bg-success',
      warn: 'bg-warn',
      info: 'bg-info',
      error: 'bg-error',
    };
    const a = this.accent();
    return a === 'none' ? '' : map[a];
  });
}
