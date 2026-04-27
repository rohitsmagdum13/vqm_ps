import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { DomSanitizer, type SafeHtml } from '@angular/platform-browser';
import { Router } from '@angular/router';
import { EmailsStore } from '../../data/emails.store';
import { ToastService } from '../../core/notifications/toast.service';
import type {
  MailAttachment,
  MailChain,
  MailItem,
  MailPriority,
  MailStatus,
} from '../../shared/models/email';

interface ItemView {
  readonly key: string;
  readonly item: MailItem;
  readonly senderName: string;
  readonly initials: string;
  readonly timestamp: string;
  readonly paragraphs: readonly string[];
  readonly html: SafeHtml | null;
}

const BLOCKED_TAG_RE = /<\/?(?:script|style|iframe|object|embed|link|meta|base|form)\b[^>]*>/gi;
const EVENT_HANDLER_ATTR_RE = /\son[a-z]+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi;
const JAVASCRIPT_URL_ATTR_RE = /(\s(?:href|src|xlink:href|action|formaction|background|poster|srcdoc)\s*=\s*)(?:"\s*javascript:[^"]*"|'\s*javascript:[^']*'|javascript:[^\s>]+)/gi;

function sanitizeHtml(raw: string): string {
  return raw
    .replace(BLOCKED_TAG_RE, '')
    .replace(EVENT_HANDLER_ATTR_RE, '')
    .replace(JAVASCRIPT_URL_ATTR_RE, '$1"#"');
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

function formatSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let size = bytes;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(size >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function iconForFormat(format: string): string {
  const f = format.toUpperCase();
  if (f === 'PDF') return '📕';
  if (f === 'XLSX' || f === 'XLS' || f === 'CSV') return '📊';
  if (f === 'DOCX' || f === 'DOC') return '📄';
  if (f === 'PNG' || f === 'JPG' || f === 'JPEG' || f === 'GIF') return '🖼️';
  if (f === 'ZIP' || f === 'RAR' || f === '7Z') return '🗜️';
  return '📎';
}

@Component({
  selector: 'app-message-viewer',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @let c = chain();
    <section
      class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm flex flex-col min-h-0 overflow-hidden"
    >
      @if (!c) {
        <div class="flex-1 flex flex-col items-center justify-center gap-2 p-10 text-center">
          <div class="text-5xl" aria-hidden="true">✉️</div>
          <div class="text-sm font-semibold text-fg">Select a mail chain</div>
          <p class="max-w-sm text-xs text-fg-dim">
            Pick a conversation from the list to read all messages, view attachments, and jump to the
            linked VQMS query.
          </p>
        </div>
      } @else {
        <header class="flex items-start gap-3 px-5 py-4 border-b border-border-light">
          <div class="flex-1 min-w-0">
            <h2 class="text-base font-semibold text-fg leading-snug">{{ subject() }}</h2>
            <div class="mt-2 flex flex-wrap gap-1.5 items-center">
              <span
                class="text-[9px] font-mono uppercase tracking-wider rounded-full px-1.5 py-0.5 border"
                [class]="statusClass(c.status)"
              >{{ c.status }}</span>
              <span
                class="text-[9px] font-mono uppercase tracking-wider rounded-full px-1.5 py-0.5 border"
                [class]="priorityClass(c.priority)"
              >{{ c.priority }}</span>
              @if (items().length > 1) {
                <span
                  class="text-[9px] font-mono uppercase tracking-wider rounded-full px-1.5 py-0.5 border bg-surface-2 text-fg-dim border-border-light"
                >💬 {{ items().length }} messages</span>
              }
              @if (c.conversation_id) {
                <button
                  type="button"
                  (click)="copyConversationId(c.conversation_id)"
                  class="text-[9px] font-mono uppercase tracking-wider rounded-full px-1.5 py-0.5 border bg-surface-2 text-fg-dim border-border-light hover:text-fg hover:bg-surface transition"
                  [attr.title]="c.conversation_id"
                >🆔 Copy conversation ID</button>
              }
            </div>
          </div>
          <div class="flex items-center gap-1 shrink-0">
            @if (detailLoading()) {
              <span class="text-[10px] font-mono text-fg-dim">Loading…</span>
            }
          </div>
        </header>

        <div class="flex-1 min-h-0 overflow-y-auto divide-y divide-border-light">
          @for (v of items(); track v.key) {
            <article class="px-5 py-4">
              <div class="flex items-start gap-3">
                <span
                  class="h-10 w-10 shrink-0 rounded-full flex items-center justify-center text-xs font-semibold text-surface bg-primary"
                  aria-hidden="true"
                >{{ v.initials }}</span>
                <div class="flex-1 min-w-0">
                  <div class="flex items-baseline gap-2 flex-wrap">
                    <span class="text-sm font-semibold text-fg">{{ v.senderName }}</span>
                    <span class="text-[11px] font-mono text-fg-dim truncate">&lt;{{ v.item.sender.email }}&gt;</span>
                  </div>
                  <div class="mt-0.5 flex items-center gap-2 text-[11px] text-fg-dim">
                    <span class="font-mono">{{ v.timestamp }}</span>
                    <span class="font-mono uppercase tracking-wider">· {{ v.item.thread_status }}</span>
                  </div>
                </div>
              </div>

              @if (v.html) {
                <div
                  class="mt-3 text-sm text-fg leading-relaxed email-html-body"
                  [innerHTML]="v.html"
                ></div>
              } @else if (v.paragraphs.length > 0) {
                <div class="mt-3 space-y-3 text-sm text-fg leading-relaxed">
                  @for (para of v.paragraphs; track $index) {
                    <p class="whitespace-pre-wrap">{{ para }}</p>
                  }
                </div>
              }

              @if (v.item.attachments.length > 0) {
                <div class="mt-4">
                  <div class="text-[10px] font-mono uppercase tracking-wider text-fg-dim mb-2">
                    Attachments
                  </div>
                  <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    @for (a of v.item.attachments; track a.attachment_id) {
                      <div
                        class="flex items-center gap-3 rounded-[var(--radius-sm)] bg-surface-2 border border-border-light px-3 py-2"
                      >
                        <span class="text-xl" aria-hidden="true">{{ iconFor(a.file_format) }}</span>
                        <div class="min-w-0 flex-1">
                          <div class="text-xs font-medium text-fg truncate" [attr.title]="a.filename">{{ a.filename }}</div>
                          <div class="text-[11px] text-fg-dim">{{ sizeLabel(a.size_bytes) }} · {{ a.file_format }}</div>
                        </div>
                        <button
                          type="button"
                          (click)="download(v.item.query_id, a)"
                          class="inline-flex items-center gap-1 rounded-[var(--radius-sm)] border border-border-light text-fg text-[11px] font-semibold px-2 py-1 hover:bg-surface transition"
                        >⬇ Download</button>
                      </div>
                    }
                  </div>
                </div>
              }
            </article>
          }
        </div>

        <footer class="flex flex-wrap items-center gap-2 px-5 py-3 border-t border-border-light">
          @if (leadQueryId()) {
            <button
              type="button"
              (click)="openQuery(leadQueryId())"
              class="ml-auto inline-flex items-center gap-2 rounded-[var(--radius-sm)] border border-primary/30 text-primary text-xs font-semibold px-3 py-2 hover:bg-primary/10 transition"
            >
              Open {{ leadQueryId() }} →
            </button>
          }
        </footer>
      }
    </section>
  `,
})
export class MessageViewer {
  readonly #store = inject(EmailsStore);
  readonly #toast = inject(ToastService);
  readonly #router = inject(Router);
  readonly #sanitizer = inject(DomSanitizer);

  protected readonly chain = computed<MailChain | null>(() => this.#store.selectedChain());
  protected readonly detailLoading = this.#store.detailLoading;

  protected readonly items = computed<readonly ItemView[]>(() => {
    const c = this.chain();
    if (!c) return [];
    const sorted = [...c.mail_items].sort((a, b) => {
      const ta = new Date(a.timestamp).getTime();
      const tb = new Date(b.timestamp).getTime();
      if (Number.isNaN(ta) || Number.isNaN(tb)) return 0;
      return ta - tb;
    });
    return sorted.map((item, idx) => {
      const senderName = item.sender.name?.trim() || item.sender.email || 'Unknown sender';
      const paragraphs = (item.body ?? '')
        .split(/\n{2,}/)
        .map((s) => s.trim())
        .filter((s) => s.length > 0);
      const rawHtml = item.body_html?.trim() ?? '';
      const html = rawHtml.length > 0
        ? this.#sanitizer.bypassSecurityTrustHtml(sanitizeHtml(rawHtml))
        : null;
      return {
        key: item.query_id || `${idx}`,
        item,
        senderName,
        initials: initialsOf(senderName),
        timestamp: formatTimestamp(item.timestamp),
        paragraphs,
        html,
      };
    });
  });

  protected readonly subject = computed<string>(() => {
    const firstItem = this.items()[0]?.item;
    return firstItem?.subject ?? '(no subject)';
  });

  protected readonly leadQueryId = computed<string>(() => {
    const sel = this.#store.selectedQueryId();
    if (sel) return sel;
    return this.items()[0]?.item.query_id ?? '';
  });

  protected iconFor(format: string): string {
    return iconForFormat(format);
  }

  protected sizeLabel(bytes: number): string {
    return formatSize(bytes);
  }

  protected async download(queryId: string, attachment: MailAttachment): Promise<void> {
    if (!queryId || !attachment.attachment_id) return;
    try {
      await this.#store.downloadAttachment(queryId, attachment.attachment_id);
      this.#toast.show(`Downloading ${attachment.filename}`, 'info');
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Download failed';
      this.#toast.show(msg, 'error');
    }
  }

  protected copyConversationId(id: string): void {
    if (typeof navigator !== 'undefined' && navigator.clipboard) {
      void navigator.clipboard.writeText(id).then(
        () => this.#toast.show('Conversation ID copied', 'success'),
        () => this.#toast.show('Clipboard unavailable', 'warn'),
      );
    } else {
      this.#toast.show('Clipboard unavailable', 'warn');
    }
  }

  protected openQuery(id: string): void {
    if (!id) return;
    // Email view is admin-only — route to the admin query detail.
    void this.#router.navigate(['/admin/queries', id]);
  }

  protected statusClass(s: MailStatus): string {
    if (s === 'New') return 'bg-warn/15 text-warn border-warn/30';
    if (s === 'Reopened') return 'bg-info/15 text-info border-info/30';
    return 'bg-success/15 text-success border-success/30';
  }

  protected priorityClass(p: MailPriority): string {
    if (p === 'High') return 'bg-red-500/15 text-red-700 border-red-500/40';
    if (p === 'Medium') return 'bg-amber-500/15 text-amber-800 border-amber-500/40';
    return 'bg-slate-500/15 text-slate-700 border-slate-500/40';
  }
}
