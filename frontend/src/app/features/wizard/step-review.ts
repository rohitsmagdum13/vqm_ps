import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { AuthService } from '../../core/auth/auth.service';
import { qtypeById } from '../../data/qtypes.data';
import { SLA_BY_PRIORITY, type WizardDraft } from './wizard.model';

interface ReviewRow {
  readonly k: string;
  readonly v: string;
}

@Component({
  selector: 'app-wizard-step-review',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="space-y-4">
      <div
        class="rounded-[var(--radius-md)] bg-surface-2 border border-border-light divide-y divide-border-light overflow-hidden"
      >
        @for (row of rows(); track row.k) {
          <div class="grid grid-cols-[120px_1fr] gap-3 px-4 py-2.5 text-sm">
            <div class="text-[10px] font-mono tracking-wider uppercase text-fg-dim pt-0.5">
              {{ row.k }}
            </div>
            <div class="text-fg">{{ row.v }}</div>
          </div>
        }
      </div>

      @if (attachments().length > 0) {
        <div
          class="rounded-[var(--radius-md)] bg-surface-2 border border-border-light overflow-hidden"
        >
          <div class="px-4 py-2 text-[10px] font-mono tracking-wider uppercase text-fg-dim border-b border-border-light">
            Attachments ({{ attachments().length }})
          </div>
          <ul class="divide-y divide-border-light">
            @for (a of attachments(); track a.name + ':' + a.size) {
              <li class="flex items-center gap-2 px-4 py-2 text-xs">
                <span class="text-base" aria-hidden="true">📎</span>
                <span class="text-fg flex-1 truncate" [title]="a.name">{{ a.name }}</span>
                <span class="font-mono text-fg-dim">{{ sizeLabel(a.size) }}</span>
              </li>
            }
          </ul>
        </div>
      }

      <div
        class="flex items-center gap-3 rounded-[var(--radius-md)] border border-success/20 bg-success/5 px-4 py-3"
      >
        <span class="text-2xl" aria-hidden="true">⏱️</span>
        <div>
          <div class="text-xs font-semibold text-success">
            Expected SLA: {{ slaLabel() }}
          </div>
          <div class="text-[11px] text-fg-dim mt-0.5">
            Auto-triaged and routed to the AI pipeline immediately after submission.
          </div>
        </div>
      </div>
    </div>
  `,
})
export class WizardStepReview {
  readonly draft = input.required<WizardDraft>();
  readonly #auth = inject(AuthService);

  protected readonly slaLabel = computed(() => SLA_BY_PRIORITY[this.draft().priority]);
  protected readonly attachments = computed<readonly File[]>(() => this.draft().files);

  protected readonly rows = computed<readonly ReviewRow[]>(() => {
    const d = this.draft();
    const t = qtypeById(d.type);
    const typeText = t ? `${t.ico} ${t.lbl}` : '—';
    const desc = d.desc.length > 80 ? `${d.desc.slice(0, 80)}…` : d.desc || '—';
    return [
      { k: 'Query Type', v: typeText },
      { k: 'Subject', v: d.subject || '—' },
      { k: 'Description', v: desc },
      { k: 'Priority', v: d.priority },
      { k: 'Reference', v: d.ref || '—' },
      { k: 'Assigned to', v: 'Auto-triaged by AI' },
      { k: 'Company', v: this.#auth.user().company },
    ];
  });

  protected sizeLabel(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
}
