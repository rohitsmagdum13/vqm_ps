import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { EmailsStore } from '../../data/emails.store';
import type { MailStatus } from '../../shared/models/email';

type CardId = 'all' | 'new' | 'reopened' | 'resolved';

interface SummaryCardView {
  readonly id: CardId;
  readonly label: string;
  readonly sub: string;
  readonly accent: 'primary' | 'warn' | 'info' | 'success';
}

const CARDS: readonly SummaryCardView[] = [
  { id: 'all', label: 'All mail', sub: 'All email-sourced queries', accent: 'primary' },
  { id: 'new', label: 'New', sub: 'Awaiting triage', accent: 'warn' },
  { id: 'reopened', label: 'Reopened', sub: 'Re-opened queries', accent: 'info' },
  { id: 'resolved', label: 'Resolved', sub: 'Closed / completed', accent: 'success' },
];

@Component({
  selector: 'app-summary-cards',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="grid grid-cols-2 md:grid-cols-4 gap-8">
      @for (c of cards; track c.id) {
        <button
          type="button"
          (click)="select(c.id)"
          [attr.aria-pressed]="isActive(c.id)"
          class="relative overflow-hidden rounded-[var(--radius-md)] bg-surface border shadow-sm px-4 py-3 text-left transition"
          [class]="cardBorder(c.id)"
        >
          <span
            class="absolute left-0 top-0 bottom-0 w-1"
            [class]="accentBg(c.accent)"
            aria-hidden="true"
          ></span>
          <div class="text-[10px] font-mono uppercase tracking-wider text-fg-dim">{{ c.label }}</div>
          <div
            class="mt-1 text-2xl font-semibold tracking-tight"
            [class]="valueClass(c.accent)"
          >
            {{ count(c.id) }}
          </div>
          <div class="mt-0.5 text-[11px] text-fg-dim">{{ c.sub }}</div>
        </button>
      }
    </div>
  `,
})
export class SummaryCards {
  readonly #store = inject(EmailsStore);
  protected readonly cards = CARDS;

  protected count(id: CardId): number {
    return this.#store.filterCounts()[id];
  }

  protected isActive(id: CardId): boolean {
    const current = this.#store.status();
    if (id === 'all') return current === null;
    return current === this.toStatus(id);
  }

  protected select(id: CardId): void {
    this.#store.setStatus(id === 'all' ? null : this.toStatus(id));
  }

  private toStatus(id: Exclude<CardId, 'all'>): MailStatus {
    if (id === 'new') return 'New';
    if (id === 'reopened') return 'Reopened';
    return 'Resolved';
  }

  protected cardBorder(id: CardId): string {
    return this.isActive(id)
      ? 'border-primary ring-2 ring-primary/20'
      : 'border-border-light hover:border-border-dark/50';
  }

  protected accentBg(a: SummaryCardView['accent']): string {
    const map: Record<SummaryCardView['accent'], string> = {
      primary: 'bg-primary',
      warn: 'bg-warn',
      info: 'bg-info',
      success: 'bg-success',
    };
    return map[a];
  }

  protected valueClass(a: SummaryCardView['accent']): string {
    const map: Record<SummaryCardView['accent'], string> = {
      primary: 'text-fg',
      warn: 'text-warn',
      info: 'text-info',
      success: 'text-success',
    };
    return map[a];
  }
}
