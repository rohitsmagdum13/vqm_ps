import { ChangeDetectionStrategy, Component, input } from '@angular/core';

@Component({
  selector: 'ui-empty-state',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div
      class="flex flex-col items-center justify-center text-center py-10 px-6 rounded-[var(--radius-md)] border border-dashed border-border-light bg-surface"
    >
      <div class="text-3xl mb-3" aria-hidden="true">{{ icon() }}</div>
      <div class="text-sm font-semibold text-fg mb-1">{{ title() }}</div>
      @if (message()) {
        <div class="text-xs text-fg-dim max-w-sm">{{ message() }}</div>
      }
      <div class="mt-4">
        <ng-content />
      </div>
    </div>
  `,
})
export class EmptyStateComponent {
  readonly title = input.required<string>();
  readonly message = input<string>('');
  readonly icon = input<string>('📭');
}
