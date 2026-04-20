import { ChangeDetectionStrategy, Component, computed, effect, inject } from '@angular/core';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { toSignal } from '@angular/core/rxjs-interop';
import { debounceTime, distinctUntilChanged } from 'rxjs';
import { EmailsStore } from '../../data/emails.store';
import type { MailChain, MailPriority, MailStatus } from '../../shared/models/email';

interface ChainRow {
  readonly key: string;
  readonly chain: MailChain;
  readonly lead: {
    readonly senderName: string;
    readonly initials: string;
    readonly subject: string;
    readonly preview: string;
    readonly timestamp: string;
    readonly queryId: string;
  };
  readonly attachmentCount: number;
}

const TIME_FMT = new Intl.DateTimeFormat('en-IN', {
  dateStyle: 'medium',
  timeStyle: 'short',
});

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return TIME_FMT.format(d);
}

function initialsOf(name: string): string {
  const trimmed = name.trim();
  if (trimmed.length === 0) return '?';
  return (
    trimmed
      .split(/\s+/)
      .map((w) => w[0] ?? '')
      .slice(0, 2)
      .join('')
      .toUpperCase() || '?'
  );
}

@Component({
  selector: 'app-message-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  template: `
    <section
      class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm flex flex-col min-h-0 overflow-hidden"
    >
      <header class="flex items-center gap-3 px-4 py-3 border-b border-border-light">
        <div class="min-w-0">
          <h2 class="text-sm font-semibold text-fg truncate">{{ title() }}</h2>
          <p class="mt-0.5 text-[11px] text-fg-dim">{{ countLabel() }}</p>
        </div>
      </header>

      <div class="px-4 pt-3 pb-2">
        <label class="flex items-center gap-2 rounded-[var(--radius-sm)] bg-surface-2 border border-border-light px-3 py-2">
          <span class="text-fg-dim text-sm" aria-hidden="true">🔍</span>
          <input
            type="search"
            [formControl]="searchCtrl"
            placeholder="Search subject, body, sender"
            class="flex-1 bg-transparent outline-none text-sm placeholder:text-fg-dim"
          />
        </label>
      </div>

      <div class="flex-1 min-h-0 overflow-y-auto divide-y divide-border-light">
        @if (rows().length === 0) {
          <div class="p-10 text-center text-xs text-fg-dim">
            @if (store.loading()) {
              Loading mail…
            } @else {
              No mail chains match your filter.
            }
          </div>
        } @else {
          @for (r of rows(); track r.key) {
            <button
              type="button"
              (click)="openChain(r.lead.queryId)"
              class="w-full text-left flex items-start gap-3 px-4 py-3 transition"
              [class]="rowClass(r.lead.queryId)"
            >
              <span
                class="h-9 w-9 shrink-0 rounded-full flex items-center justify-center text-[11px] font-semibold text-surface bg-primary"
                aria-hidden="true"
              >{{ r.lead.initials }}</span>
              <span class="flex-1 min-w-0">
                <span class="flex items-center justify-between gap-2">
                  <span class="text-sm font-semibold text-fg truncate">{{ r.lead.senderName }}</span>
                  <span class="text-[11px] font-mono text-fg-dim shrink-0">{{ r.lead.timestamp }}</span>
                </span>
                <span class="mt-0.5 flex items-center gap-1.5 flex-wrap">
                  <span class="text-[13px] font-semibold text-fg truncate">{{ r.lead.subject }}</span>
                  @if (r.chain.mail_items.length > 1) {
                    <span
                      class="text-[9px] font-mono uppercase tracking-wider rounded-full px-1.5 py-0.5 border bg-surface-2 text-fg-dim border-border-light"
                    >💬 {{ r.chain.mail_items.length }}</span>
                  }
                </span>
                <span class="mt-0.5 block text-[11px] text-fg-dim line-clamp-2">{{ r.lead.preview }}</span>
                <span class="mt-1.5 flex flex-wrap gap-1">
                  <span
                    class="text-[9px] font-mono uppercase tracking-wider rounded-full px-1.5 py-0.5 border"
                    [class]="statusClass(r.chain.status)"
                  >{{ r.chain.status }}</span>
                  <span
                    class="text-[9px] font-mono uppercase tracking-wider rounded-full px-1.5 py-0.5 border"
                    [class]="priorityClass(r.chain.priority)"
                  >{{ r.chain.priority }}</span>
                  @if (r.attachmentCount > 0) {
                    <span
                      class="text-[9px] font-mono uppercase tracking-wider rounded-full px-1.5 py-0.5 border bg-surface-2 text-fg-dim border-border-light"
                    >📎 {{ r.attachmentCount }}</span>
                  }
                </span>
              </span>
            </button>
          }
        }
      </div>

      <footer class="flex items-center justify-between gap-2 px-4 py-2 border-t border-border-light text-xs">
        <button
          type="button"
          (click)="prev()"
          [disabled]="store.page() <= 1 || store.loading()"
          class="rounded-[var(--radius-sm)] border border-border-light px-2 py-1 text-fg hover:bg-surface-2 disabled:opacity-40 disabled:cursor-not-allowed transition"
        >← Prev</button>
        <span class="font-mono text-fg-dim">
          Page {{ store.page() }} of {{ store.totalPages() }}
        </span>
        <button
          type="button"
          (click)="next()"
          [disabled]="!canNext() || store.loading()"
          class="rounded-[var(--radius-sm)] border border-border-light px-2 py-1 text-fg hover:bg-surface-2 disabled:opacity-40 disabled:cursor-not-allowed transition"
        >Next →</button>
      </footer>
    </section>
  `,
})
export class MessageList {
  protected readonly store = inject(EmailsStore);

  protected readonly searchCtrl = new FormControl<string>('', { nonNullable: true });
  readonly #searchValue = toSignal(
    this.searchCtrl.valueChanges.pipe(debounceTime(300), distinctUntilChanged()),
    { initialValue: '' },
  );

  constructor() {
    effect(() => {
      const v = this.#searchValue();
      this.store.setSearch(v);
    });
  }

  protected readonly rows = computed<readonly ChainRow[]>(() =>
    this.store.chains().map((chain) => {
      const lead = chain.mail_items[0];
      const attachmentCount = chain.mail_items.reduce(
        (sum, item) => sum + item.attachments.length,
        0,
      );
      const senderName = lead?.sender.name?.trim() || lead?.sender.email || 'Unknown sender';
      const preview = (lead?.body ?? '').replace(/\s+/g, ' ').slice(0, 160);
      return {
        key: chain.conversation_id ?? lead?.query_id ?? `chain-${Math.random()}`,
        chain,
        lead: {
          senderName,
          initials: initialsOf(senderName),
          subject: lead?.subject ?? '(no subject)',
          preview,
          timestamp: lead ? formatTimestamp(lead.timestamp) : '',
          queryId: lead?.query_id ?? '',
        },
        attachmentCount,
      };
    }),
  );

  protected readonly title = computed<string>(() => {
    const s = this.store.status();
    if (s === null) return 'All mail';
    return s;
  });

  protected readonly countLabel = computed<string>(() => {
    const t = this.store.total();
    return `${t} chain${t === 1 ? '' : 's'}`;
  });

  protected readonly canNext = computed<boolean>(() => {
    return this.store.page() * this.store.pageSize() < this.store.total();
  });

  protected openChain(queryId: string): void {
    if (!queryId) return;
    this.store.selectChain(queryId);
  }

  protected prev(): void {
    this.store.setPage(this.store.page() - 1);
  }

  protected next(): void {
    this.store.setPage(this.store.page() + 1);
  }

  protected rowClass(queryId: string): string {
    return this.store.selectedQueryId() === queryId
      ? 'bg-primary/10 hover:bg-primary/10'
      : 'bg-surface hover:bg-surface-2';
  }

  protected statusClass(s: MailStatus): string {
    if (s === 'New') return 'bg-warn/15 text-warn border-warn/30';
    if (s === 'Reopened') return 'bg-info/15 text-info border-info/30';
    return 'bg-success/15 text-success border-success/30';
  }

  protected priorityClass(p: MailPriority): string {
    if (p === 'High') return 'bg-red-500/15 text-red-700 border border-red-500/40';
    if (p === 'Medium') return 'bg-amber-500/15 text-amber-800 border border-amber-500/40';
    return 'bg-slate-500/15 text-slate-700 border border-slate-500/40';
  }
}
