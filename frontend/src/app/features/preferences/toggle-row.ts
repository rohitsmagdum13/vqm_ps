import { ChangeDetectionStrategy, Component, inject, input } from '@angular/core';
import { PreferencesStore } from '../../data/preferences.store';
import { ToggleComponent } from '../../shared/ui/toggle/toggle';
import type { PrefToggleRow } from './preferences.data';

@Component({
  selector: 'app-toggle-row',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ToggleComponent],
  template: `
    <div
      class="flex items-center gap-3 rounded-[var(--radius-sm)] border border-border-light bg-surface px-4 py-3"
    >
      <div class="min-w-0 flex-1">
        <div class="text-sm font-medium text-fg">{{ row().label }}</div>
        <div class="mt-0.5 text-[11px] text-fg-dim">{{ row().desc }}</div>
      </div>
      <ui-toggle
        [checked]="isOn()"
        (checkedChange)="onChange($event)"
        [label]="row().label"
      />
    </div>
  `,
})
export class ToggleRow {
  readonly row = input.required<PrefToggleRow>();

  readonly #store = inject(PreferencesStore);

  protected isOn(): boolean {
    return this.#store.toggles()[this.row().id] ?? false;
  }

  protected onChange(next: boolean): void {
    this.#store.setToggle(this.row().id, next);
  }
}
