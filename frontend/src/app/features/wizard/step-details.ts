import { ChangeDetectionStrategy, Component, computed, effect, inject, input, model, output } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { toSignal } from '@angular/core/rxjs-interop';
import type { Priority } from '../../shared/models/query';
import { qtypeById } from '../../data/qtypes.data';

const PRIORITIES: readonly Priority[] = ['Critical', 'High', 'Medium', 'Low'];

@Component({
  selector: 'app-wizard-step-details',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  template: `
    <div class="space-y-4">
      <div
        class="flex items-center gap-2 rounded-[var(--radius-sm)] bg-primary/5 border border-primary/20 px-3 py-2 text-xs"
      >
        <span class="text-base">{{ typeIcon() }}</span>
        <strong class="text-fg">{{ typeLabel() }}</strong>
        <button
          type="button"
          (click)="changeType.emit()"
          class="ml-auto text-[10px] text-fg-dim hover:text-primary transition"
        >
          Change
        </button>
      </div>

      <form [formGroup]="form" class="space-y-4">
        <div>
          <label for="ws-subj" class="block text-[10px] font-mono tracking-wider uppercase text-fg-dim mb-1">
            Subject *
          </label>
          <input
            id="ws-subj"
            type="text"
            formControlName="subject"
            placeholder="Brief description of the issue"
            class="w-full rounded-[var(--radius-sm)] bg-surface-2 border border-border-light text-sm text-fg px-3 py-2 focus:outline-none focus:border-primary"
          />
        </div>

        <div>
          <label for="ws-desc" class="block text-[10px] font-mono tracking-wider uppercase text-fg-dim mb-1">
            Description *
          </label>
          <textarea
            id="ws-desc"
            rows="4"
            formControlName="desc"
            placeholder="Include clause numbers, dates, order IDs, amounts…"
            class="w-full rounded-[var(--radius-sm)] bg-surface-2 border border-border-light text-sm text-fg px-3 py-2 focus:outline-none focus:border-primary resize-y"
          ></textarea>
          <div class="mt-1 text-[10px] font-mono text-fg-dim text-right">{{ descLen() }}/1000</div>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <div class="block text-[10px] font-mono tracking-wider uppercase text-fg-dim mb-1">Priority</div>
            <div class="flex flex-wrap gap-2">
              @for (p of priorities; track p) {
                <button
                  type="button"
                  (click)="priority.set(p)"
                  class="rounded-[var(--radius-sm)] border px-3 py-1.5 text-xs font-medium transition"
                  [class]="priClass(p)"
                >
                  {{ p }}
                </button>
              }
            </div>
          </div>

          <div>
            <label for="ws-ref" class="block text-[10px] font-mono tracking-wider uppercase text-fg-dim mb-1">
              Reference (optional)
            </label>
            <input
              id="ws-ref"
              type="text"
              formControlName="ref"
              placeholder="PO #, Contract ID, Ticket #…"
              class="w-full rounded-[var(--radius-sm)] bg-surface-2 border border-border-light text-sm text-fg px-3 py-2 focus:outline-none focus:border-primary"
            />
          </div>
        </div>
      </form>
    </div>
  `,
})
export class WizardStepDetails {
  readonly typeId = input.required<string>();
  readonly subject = model.required<string>();
  readonly desc = model.required<string>();
  readonly priority = model.required<Priority>();
  readonly ref = model.required<string>();
  readonly changeType = output<void>();

  protected readonly priorities = PRIORITIES;

  readonly #fb = inject(FormBuilder);
  protected readonly form = this.#fb.nonNullable.group({
    subject: ['', [Validators.required, Validators.minLength(3)]],
    desc: ['', [Validators.required, Validators.minLength(10), Validators.maxLength(1000)]],
    ref: [''],
  });

  readonly #values = toSignal(this.form.valueChanges, { initialValue: this.form.getRawValue() });

  protected readonly descLen = computed(() => (this.#values().desc ?? '').length);
  protected readonly typeLabel = computed(() => qtypeById(this.typeId())?.lbl ?? 'Query');
  protected readonly typeIcon = computed(() => qtypeById(this.typeId())?.ico ?? '💬');

  constructor() {
    effect(() => {
      const s = this.subject();
      const d = this.desc();
      const r = this.ref();
      const cur = this.form.getRawValue();
      if (cur.subject !== s || cur.desc !== d || cur.ref !== r) {
        this.form.patchValue({ subject: s, desc: d, ref: r }, { emitEvent: false });
      }
    });

    effect(() => {
      const v = this.#values();
      this.subject.set(v.subject ?? '');
      this.desc.set(v.desc ?? '');
      this.ref.set(v.ref ?? '');
    });
  }

  protected priClass(p: Priority): string {
    const selected = this.priority() === p;
    const map: Record<Priority, { on: string; off: string }> = {
      Critical: { on: 'bg-error/10 text-error border-error', off: 'bg-surface text-fg-dim border-border-light hover:border-error/40' },
      High: { on: 'bg-warn/10 text-warn border-warn', off: 'bg-surface text-fg-dim border-border-light hover:border-warn/40' },
      Medium: { on: 'bg-info/10 text-info border-info', off: 'bg-surface text-fg-dim border-border-light hover:border-info/40' },
      Low: { on: 'bg-success/10 text-success border-success', off: 'bg-surface text-fg-dim border-border-light hover:border-success/40' },
    };
    return selected ? map[p].on : map[p].off;
  }
}
