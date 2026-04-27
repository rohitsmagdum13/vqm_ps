import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  model,
  output,
  signal,
} from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { toSignal } from '@angular/core/rxjs-interop';
import type { Priority } from '../../shared/models/query';
import { qtypeById } from '../../data/qtypes.data';
import {
  BLOCKED_ATTACHMENT_EXTENSIONS,
  MAX_ATTACHMENT_BYTES,
  MAX_ATTACHMENT_COUNT,
  MAX_TOTAL_ATTACHMENT_BYTES,
} from './wizard.model';

const PRIORITIES: readonly Priority[] = ['Critical', 'High', 'Medium', 'Low'];

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fileExt(name: string): string {
  const idx = name.lastIndexOf('.');
  return idx >= 0 ? name.slice(idx).toLowerCase() : '';
}

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

        <div>
          <div class="block text-[10px] font-mono tracking-wider uppercase text-fg-dim mb-1">
            Attachments (optional)
          </div>
          <label
            for="ws-files"
            class="flex flex-col items-center justify-center gap-1 rounded-[var(--radius-sm)] border-2 border-dashed border-border-light bg-surface-2 px-4 py-5 cursor-pointer hover:border-primary/60 hover:bg-surface transition"
          >
            <span class="text-2xl" aria-hidden="true">📎</span>
            <span class="text-xs text-fg">Click to select files</span>
            <span class="text-[10px] text-fg-dim">
              PDF, DOCX, XLSX, CSV, TXT, PNG, JPG · max
              {{ maxCount }} files · 10 MB each · 50 MB total
            </span>
            <input
              id="ws-files"
              type="file"
              multiple
              class="hidden"
              [accept]="acceptList"
              (change)="onFilesSelected($event)"
            />
          </label>

          @if (files().length > 0) {
            <ul class="mt-2 space-y-1">
              @for (f of files(); track f.name + ':' + f.size; let i = $index) {
                <li
                  class="flex items-center gap-2 rounded-[var(--radius-sm)] bg-surface-2 border border-border-light px-3 py-1.5 text-xs"
                >
                  <span class="text-base" aria-hidden="true">{{ fileIcon(f.name) }}</span>
                  <span class="text-fg truncate flex-1" [title]="f.name">{{ f.name }}</span>
                  <span class="font-mono text-fg-dim">{{ sizeLabel(f.size) }}</span>
                  <button
                    type="button"
                    (click)="removeFile(i)"
                    class="text-fg-dim hover:text-error transition"
                    aria-label="Remove file"
                  >
                    ✕
                  </button>
                </li>
              }
            </ul>
          }

          @if (fileError()) {
            <div class="mt-2 text-[11px] text-error">{{ fileError() }}</div>
          }
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
  readonly files = model.required<readonly File[]>();
  readonly changeType = output<void>();

  protected readonly priorities = PRIORITIES;
  protected readonly maxCount = MAX_ATTACHMENT_COUNT;
  protected readonly fileError = signal<string | null>(null);

  // Limits the file picker dialog to the same set the backend accepts.
  // The backend still re-validates server-side — this is purely UX.
  protected readonly acceptList =
    '.pdf,.docx,.xlsx,.xls,.csv,.txt,.png,.jpg,.jpeg,.tiff,application/pdf';

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

  protected onFilesSelected(event: Event): void {
    const input = event.target as HTMLInputElement | null;
    const picked = input?.files;
    if (!picked || picked.length === 0) {
      this.fileError.set(null);
      return;
    }
    // Build the new list off existing files so re-opening the picker
    // appends instead of replaces — matches what most users expect when
    // they realise they forgot one.
    const merged: File[] = [...this.files()];
    let error: string | null = null;
    for (let i = 0; i < picked.length; i += 1) {
      const f = picked.item(i);
      if (!f) continue;
      const validation = this.validateFile(f, merged);
      if (validation) {
        error = validation;
        continue;
      }
      merged.push(f);
    }
    this.files.set(Object.freeze(merged));
    this.fileError.set(error);
    // Reset the input so the same file can be re-picked after removal.
    if (input) input.value = '';
  }

  protected removeFile(index: number): void {
    const next = this.files().filter((_, i) => i !== index);
    this.files.set(Object.freeze(next));
    this.fileError.set(null);
  }

  protected sizeLabel(bytes: number): string {
    return formatBytes(bytes);
  }

  protected fileIcon(name: string): string {
    const ext = fileExt(name);
    if (ext === '.pdf') return '📄';
    if (ext === '.docx' || ext === '.doc') return '📝';
    if (ext === '.xlsx' || ext === '.xls' || ext === '.csv') return '📊';
    if (ext === '.png' || ext === '.jpg' || ext === '.jpeg' || ext === '.tiff' || ext === '.tif') {
      return '🖼️';
    }
    return '📎';
  }

  private validateFile(f: File, current: readonly File[]): string | null {
    if (current.length >= MAX_ATTACHMENT_COUNT) {
      return `You can attach at most ${MAX_ATTACHMENT_COUNT} files.`;
    }
    if (BLOCKED_ATTACHMENT_EXTENSIONS.includes(fileExt(f.name))) {
      return `${f.name} — file type is not allowed.`;
    }
    if (f.size > MAX_ATTACHMENT_BYTES) {
      return `${f.name} is larger than ${formatBytes(MAX_ATTACHMENT_BYTES)}.`;
    }
    const totalAfter = current.reduce((acc, x) => acc + x.size, 0) + f.size;
    if (totalAfter > MAX_TOTAL_ATTACHMENT_BYTES) {
      return `Total attachment size exceeds ${formatBytes(MAX_TOTAL_ATTACHMENT_BYTES)}.`;
    }
    return null;
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
