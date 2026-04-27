import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import type {
  ExtractedEntities,
  SubmittedAttachment,
} from '../../data/query.service';

interface EntityRow {
  readonly label: string;
  readonly value: string;
}

@Component({
  selector: 'app-wizard-success',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="flex flex-col items-center text-center space-y-5 py-6">
      <div
        class="h-16 w-16 rounded-full bg-success/10 border-2 border-success flex items-center justify-center"
      >
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path
            d="M5 12l4 4 10-10"
            stroke="var(--color-success)"
            stroke-width="2.4"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </div>

      <div class="space-y-1">
        <h2 class="text-lg font-semibold text-fg">Query submitted</h2>
        <p class="text-sm text-fg-dim">Your query has been logged and routed to the AI pipeline.</p>
      </div>

      <div
        class="rounded-[var(--radius-sm)] bg-primary/5 border border-primary/20 px-4 py-2 font-mono text-sm text-primary"
      >
        {{ queryId() }}
      </div>

      @if (attachments().length > 0) {
        <div class="w-full rounded-[var(--radius-md)] bg-surface-2 border border-border-light p-4 text-left space-y-2">
          <div class="text-[10px] font-mono tracking-wider uppercase text-fg-dim">
            Attachments processed ({{ attachments().length }})
          </div>
          <ul class="space-y-1">
            @for (a of attachments(); track a.attachment_id) {
              <li class="flex items-center gap-2 text-xs">
                <span class="text-base" aria-hidden="true">📎</span>
                <span class="text-fg flex-1 truncate" [title]="a.filename">{{ a.filename }}</span>
                <span
                  class="font-mono text-[10px] px-1.5 py-0.5 rounded"
                  [class]="extractionBadgeClass(a.extraction_status)"
                >
                  {{ extractionLabel(a) }}
                </span>
              </li>
            }
          </ul>
        </div>
      }

      @if (entityRows().length > 0) {
        <div class="w-full rounded-[var(--radius-md)] bg-surface-2 border border-border-light p-4 text-left space-y-2">
          <div class="text-[10px] font-mono tracking-wider uppercase text-fg-dim">
            Entities extracted by AI
          </div>
          @if (entitySummary()) {
            <div class="text-xs text-fg italic">"{{ entitySummary() }}"</div>
          }
          <dl class="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1 text-xs">
            @for (row of entityRows(); track row.label) {
              <div class="flex gap-2">
                <dt class="text-fg-dim">{{ row.label }}:</dt>
                <dd class="text-fg font-mono truncate">{{ row.value }}</dd>
              </div>
            }
          </dl>
        </div>
      }

      <div class="w-full rounded-[var(--radius-md)] bg-surface-2 border border-border-light p-4 text-left space-y-2">
        <div class="text-[10px] font-mono tracking-wider uppercase text-fg-dim">What happens next</div>
        <ol class="space-y-2 text-sm text-fg">
          <li class="flex gap-2">
            <span class="text-success">✓</span>
            <span>AI classifies priority and category</span>
          </li>
          <li class="flex gap-2">
            <span class="text-success">✓</span>
            <span>Routed to the resolution queue</span>
          </li>
          <li class="flex gap-2">
            <span class="text-fg-dim">•</span>
            <span class="text-fg-dim">AI drafts a response from the knowledge base</span>
          </li>
          <li class="flex gap-2">
            <span class="text-fg-dim">•</span>
            <span class="text-fg-dim">Human reviewer approves &amp; sends</span>
          </li>
        </ol>
      </div>

      <div class="flex flex-wrap gap-2 justify-center">
        <button
          type="button"
          (click)="track.emit()"
          class="inline-flex items-center gap-1 rounded-[var(--radius-sm)] bg-primary text-surface text-xs font-medium px-4 py-2 hover:bg-secondary transition"
        >
          Track {{ queryId() }} →
        </button>
        <button
          type="button"
          (click)="newOne.emit()"
          class="inline-flex items-center gap-1 rounded-[var(--radius-sm)] bg-surface border border-border-light text-xs font-medium text-fg px-4 py-2 hover:bg-surface-2 transition"
        >
          Raise another
        </button>
        <button
          type="button"
          (click)="done.emit()"
          class="inline-flex items-center gap-1 rounded-[var(--radius-sm)] bg-surface border border-border-light text-xs font-medium text-fg-dim px-4 py-2 hover:bg-surface-2 transition"
        >
          Back to portal
        </button>
      </div>
    </div>
  `,
})
export class WizardSuccess {
  readonly queryId = input.required<string>();
  readonly attachments = input<readonly SubmittedAttachment[]>([]);
  readonly entities = input<ExtractedEntities | null>(null);
  readonly track = output<void>();
  readonly newOne = output<void>();
  readonly done = output<void>();

  protected readonly entitySummary = computed(() => this.entities()?.summary ?? '');

  /** Build a flat list of "Field: comma-separated values" rows, but
   *  only for fields that actually had matches. Empty arrays are
   *  hidden so the panel stays compact. */
  protected readonly entityRows = computed<readonly EntityRow[]>(() => {
    const e = this.entities();
    if (!e) return [];
    const rows: EntityRow[] = [];
    if (e.invoice_numbers.length) rows.push({ label: 'Invoices', value: e.invoice_numbers.join(', ') });
    if (e.po_numbers.length) rows.push({ label: 'POs', value: e.po_numbers.join(', ') });
    if (e.amounts.length) {
      rows.push({
        label: 'Amounts',
        value: e.amounts.map((a) => `${a.value} ${a.currency}`).join(', '),
      });
    }
    if (e.dates.length) rows.push({ label: 'Dates', value: e.dates.join(', ') });
    if (e.contract_ids.length) rows.push({ label: 'Contracts', value: e.contract_ids.join(', ') });
    if (e.ticket_numbers.length) rows.push({ label: 'Tickets', value: e.ticket_numbers.join(', ') });
    if (e.product_skus.length) rows.push({ label: 'SKUs', value: e.product_skus.join(', ') });
    if (e.vendor_names.length) rows.push({ label: 'Vendors', value: e.vendor_names.join(', ') });
    if (e.emails.length) rows.push({ label: 'Emails', value: e.emails.join(', ') });
    if (e.phone_numbers.length) rows.push({ label: 'Phones', value: e.phone_numbers.join(', ') });
    return rows;
  });

  protected extractionLabel(a: SubmittedAttachment): string {
    if (a.extraction_status === 'success') {
      return a.extraction_method === 'textract' ? 'OCR (Textract)' : a.extraction_method;
    }
    return a.extraction_status;
  }

  protected extractionBadgeClass(status: SubmittedAttachment['extraction_status']): string {
    switch (status) {
      case 'success':
        return 'bg-success/10 text-success';
      case 'skipped':
        return 'bg-warn/10 text-warn';
      case 'failed':
        return 'bg-error/10 text-error';
      default:
        return 'bg-fg-dim/10 text-fg-dim';
    }
  }
}
