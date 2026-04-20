import { ChangeDetectionStrategy, Component, model } from '@angular/core';
import { QTYPES } from '../../data/qtypes.data';

@Component({
  selector: 'app-wizard-step-type',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-5">
      @for (t of types; track t.id) {
        <button
          type="button"
          (click)="selected.set(t.id)"
          class="text-left rounded-[var(--radius-md)] border p-4 transition focus:outline-none focus:ring-2 focus:ring-primary/40"
          [class]="tileClass(t.id)"
        >
          <div class="text-2xl leading-none">{{ t.ico }}</div>
          <div class="mt-2 text-sm font-semibold text-fg">{{ t.lbl }}</div>
          <div class="mt-0.5 text-[11px] text-fg-dim">{{ t.sub }}</div>
        </button>
      }
    </div>
  `,
})
export class WizardStepType {
  readonly selected = model.required<string>();
  protected readonly types = QTYPES;

  protected tileClass(id: string): string {
    return this.selected() === id
      ? 'bg-primary/5 border-primary shadow-sm'
      : 'bg-surface border-border-light hover:border-primary/40 hover:bg-surface-2';
  }
}
