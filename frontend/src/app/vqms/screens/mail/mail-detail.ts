import { ChangeDetectionStrategy, Component, computed, input, output, signal } from '@angular/core';
import { Icon } from '../../ui/icon';
import { Mono } from '../../ui/mono';
import { Avatar } from '../../ui/avatar';
import { PathBadge } from '../../ui/path-badge';
import { AiDraftCard } from './ai-draft-card';
import { VendorMiniCard } from './vendor-mini-card';
import { InternalNotes } from './internal-notes';
import { InlineComposer, type ComposerMode } from './inline-composer';
import {
  MAIL_AI_DRAFTS,
  MAIL_AUDIT,
  MAIL_INTERNAL_NOTES,
  MAIL_THREAD_HISTORY,
  fmtBytes,
  fmtMailTime,
} from '../../data/mail';
import type {
  MailAuditEntry,
  MailHistoryMsg,
  MailInternalNote,
  MailThread,
} from '../../data/mail';
import { VENDORS } from '../../data/mock-data';

export type MailDetailAction = 'flag' | 'archive' | 'create_query';

// Module-level frozen empties used as stable fallbacks for the row's
// derived computeds. Returning `?? []` would create a new array on
// every evaluation, defeating signal memoisation and causing every
// downstream subscriber to think the value changed.
const EMPTY_HISTORY: readonly MailHistoryMsg[] = Object.freeze([]);
const EMPTY_AUDIT: readonly MailAuditEntry[] = Object.freeze([]);
const EMPTY_NOTES: readonly MailInternalNote[] = Object.freeze([]);

@Component({
  selector: 'vq-mail-detail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    Icon,
    Mono,
    Avatar,
    PathBadge,
    AiDraftCard,
    VendorMiniCard,
    InternalNotes,
    InlineComposer,
  ],
  host: { style: 'display: contents;' },
  template: `
    @if (!row()) {
      <div class="flex-1 flex items-center justify-center bg-bg">
        <div class="text-center fade-up">
          <div
            style="width:56px; height:56px; border-radius:999px; background: var(--panel); border: 1px solid var(--line); display:inline-flex; align-items:center; justify-content:center; margin-bottom:14px;"
          >
            <vq-icon name="mail" [size]="20" cssClass="subtle" />
          </div>
          <div class="ink" style="font-size:14px; font-weight:500;">Select a message</div>
          <div class="muted mt-1" style="font-size:12px;">
            Pick anything from the list to read the full thread.
          </div>
          <div class="muted mt-4" style="font-size:11px;">
            <vq-mono>J</vq-mono>/<vq-mono>K</vq-mono> navigate ·
            <vq-mono>R</vq-mono> reply · <vq-mono>E</vq-mono> archive ·
            <vq-mono>C</vq-mono> compose
          </div>
        </div>
      </div>
    } @else {
      <div class="flex-1 flex overflow-hidden">
        <div class="flex-1 overflow-y-auto bg-bg">
          <div class="bg-panel border-b hairline px-6 py-4">
            <div class="flex items-start gap-3">
              <div class="flex-1 min-w-0">
                <div
                  class="ink"
                  style="font-size:17px; font-weight:600; letter-spacing:-.01em; line-height:1.3;"
                >
                  {{ row()!.subject }}
                </div>
                <div class="flex items-center gap-2 mt-2 flex-wrap">
                  <vq-path-badge [letter]="row()!.processing_path" />
                  @if (row()!.ticket_id; as ticket) {
                    <a
                      class="chip"
                      href="#"
                      style="color: var(--info); border-color: var(--line);"
                    >
                      <vq-icon name="ticket" [size]="10" />
                      <vq-mono [size]="10.5">{{ ticket }}</vq-mono>
                    </a>
                  }
                  <a
                    class="chip"
                    href="#"
                    style="color: var(--accent); border-color: var(--line);"
                  >
                    <vq-icon name="link" [size]="10" />
                    <vq-mono [size]="10.5">{{ row()!.query_id }}</vq-mono>
                  </a>
                  <button class="chip" (click)="action.emit('create_query')">
                    <vq-icon name="plus" [size]="10" /> Create query
                  </button>
                  <span class="flex-1"></span>
                  <button
                    class="btn btn-ghost"
                    title="Flag"
                    (click)="action.emit('flag')"
                  >
                    <vq-icon
                      name="flag"
                      [size]="13"
                      [cssClass]="row()!._flagged ? 'text-accent' : 'muted'"
                    />
                  </button>
                  <button class="btn btn-ghost" title="Print">
                    <vq-icon name="printer" [size]="13" />
                  </button>
                  <button class="btn btn-ghost" title="More">
                    <vq-icon name="more-horizontal" [size]="13" />
                  </button>
                </div>
              </div>
            </div>

            <div
              class="grid mt-4"
              style="grid-template-columns: 80px 1fr; row-gap: 4px; column-gap: 12px; font-size:12px;"
            >
              <div class="muted">From</div>
              <div class="flex items-center gap-2">
                <vq-avatar [name]="row()!.from_name" [size]="20" />
                <span class="ink" style="font-weight:500;">{{ row()!.from_name }}</span>
                <vq-mono cssClass="muted" [size]="11">&lt;{{ row()!.from_address }}&gt;</vq-mono>
              </div>
              <div class="muted">To</div>
              <vq-mono cssClass="ink-2" [size]="11.5">{{ row()!.to_addresses.join(', ') }}</vq-mono>
              @if (row()!.cc_addresses.length > 0) {
                <div class="muted">Cc</div>
                <vq-mono cssClass="ink-2" [size]="11.5">{{ row()!.cc_addresses.join(', ') }}</vq-mono>
              }
              <div class="muted">Date</div>
              <vq-mono cssClass="ink-2" [size]="11.5">{{ dateText() }}</vq-mono>
              <div class="muted">Message‑Id</div>
              <vq-mono cssClass="muted" [size]="10.5">{{ row()!.message_id }}</vq-mono>
            </div>

            <div class="flex items-center gap-1.5 mt-4 flex-wrap">
              <button class="btn btn-primary" (click)="startReply('Reply')">
                <vq-icon name="reply" [size]="13" /> Reply
                <vq-mono [size]="10" [color]="'rgba(255,255,255,.6)'" cssClass="ml-1">R</vq-mono>
              </button>
              <button class="btn" (click)="startReply('Reply all')">
                <vq-icon name="reply-all" [size]="13" /> Reply all
              </button>
              <button class="btn" (click)="startReply('Forward')">
                <vq-icon name="corner-up-right" [size]="13" /> Forward
              </button>
              <div style="width:1px; height:22px; background: var(--line); margin: 0 4px;"></div>
              <button class="btn"><vq-icon name="user-plus" [size]="13" /> Assign</button>
              <button class="btn"><vq-icon name="alert-triangle" [size]="13" /> Escalate</button>
              <button class="btn">
                <vq-icon name="check-circle-2" [size]="13" /> Mark resolved
              </button>
              <button class="btn" (click)="action.emit('archive')">
                <vq-icon name="archive" [size]="13" /> Archive
                <vq-mono cssClass="ml-1" [size]="10">E</vq-mono>
              </button>
              <span class="flex-1"></span>
              <button class="btn btn-ghost" (click)="showAudit.set(!showAudit())">
                <vq-icon name="scroll-text" [size]="13" />
                {{ showAudit() ? 'Hide' : 'Show' }} audit
              </button>
            </div>
          </div>

          @if (ai() && row()!._direction === 'inbound') {
            <vq-mail-ai-draft-card [ai]="ai()!" (use)="startReply('AI draft')" />
          }

          <div class="px-6 py-5">
            @if (collapsedHistory().length > 0) {
              <details class="mb-3">
                <summary class="cursor-pointer muted" style="font-size:12px;">
                  <vq-icon name="history" [size]="11" />
                  {{ collapsedHistory().length }} earlier message{{
                    collapsedHistory().length === 1 ? '' : 's'
                  }}
                  in thread
                </summary>
                <div class="mt-2 space-y-2">
                  @for (m of collapsedHistory(); track m.ts + m.from_name) {
                    <div class="panel px-3 py-2" style="border-radius:4px;">
                      <div class="flex items-center gap-2">
                        <vq-avatar [name]="m.from_name" [size]="20" />
                        <span class="ink-2" style="font-size:12px; font-weight:500;">{{
                          m.from_name
                        }}</span>
                        <vq-mono cssClass="muted" [size]="10.5">{{ histTime(m.ts) }}</vq-mono>
                      </div>
                      <div class="muted truncate mt-1" style="font-size:12px;">{{ m.snippet }}</div>
                    </div>
                  }
                </div>
              </details>
            }

            <div class="panel" style="border-radius:4px;">
              <div class="px-5 py-4">
                <pre
                  class="ink-2"
                  style="font-family: inherit; white-space: pre-wrap; font-size:13px; line-height:1.65; margin:0;"
                  >{{ row()!.body_text }}</pre>

                @if (row()!.attachments.length > 0) {
                  <div class="mt-4 pt-4 border-t hairline">
                    <div
                      class="muted uppercase tracking-wider mb-2"
                      style="font-size:10px; font-weight:600;"
                    >
                      {{ row()!.attachments.length }} attachment{{
                        row()!.attachments.length === 1 ? '' : 's'
                      }}
                    </div>
                    <div class="flex flex-wrap gap-2">
                      @for (a of row()!.attachments; track a.attachment_id) {
                        <div
                          class="flex items-center gap-2 panel px-3 py-2 cursor-pointer"
                          style="border-radius:4px; background: var(--bg);"
                        >
                          <vq-icon [name]="attachIcon(a.mime_type, a.filename)" [size]="14" cssClass="muted" />
                          <div>
                            <div class="ink-2" style="font-size:12px; font-weight:500;">
                              {{ a.filename }}
                            </div>
                            <vq-mono cssClass="muted" [size]="10"
                              >{{ formatBytes(a.size_bytes) }} · S3</vq-mono
                            >
                          </div>
                          <button class="btn btn-ghost ml-2">
                            <vq-icon name="download" [size]="12" />
                          </button>
                        </div>
                      }
                    </div>
                  </div>
                }
              </div>
            </div>

            @if (showAudit() && audit().length > 0) {
              <div class="panel mt-4 fade-up" style="border-radius:4px;">
                <div class="px-4 py-2.5 border-b hairline flex items-center gap-2">
                  <vq-icon name="scroll-text" [size]="12" cssClass="muted" />
                  <span class="ink-2" style="font-size:12px; font-weight:500;">Audit trail</span>
                  <vq-mono cssClass="muted ml-auto" [size]="10">audit.action_log</vq-mono>
                </div>
                <div class="px-4 py-3">
                  @for (a of audit(); track a.ts + a.action) {
                    <div class="flex items-start gap-3 py-1.5" style="font-size:11.5px;">
                      <vq-mono cssClass="muted" [size]="10.5" style="min-width:130px;">{{ a.ts }}</vq-mono>
                      <vq-mono cssClass="muted" [size]="10.5" style="min-width:150px;">{{
                        a.actor
                      }}</vq-mono>
                      <span class="ink-2">{{ a.action }}</span>
                    </div>
                  }
                </div>
              </div>
            }
          </div>

          @if (showCompose()) {
            <vq-mail-inline-composer
              [mode]="replyMode()"
              [row]="row()!"
              [seedBody]="seedBody()"
              (closed)="showCompose.set(false)"
            />
          }
        </div>

        <aside
          class="flex-shrink-0 hidden xl:block"
          style="width:260px; border-left: 1px solid var(--line); background: var(--panel); overflow-y: auto;"
        >
          <vq-mail-vendor-card [vendor]="vendor()" />
          <vq-mail-internal-notes [notes]="notes()" [messageId]="row()!.message_id" />
        </aside>
      </div>
    }
  `,
})
export class MailDetail {
  readonly row = input<MailThread | null>(null);
  readonly action = output<MailDetailAction>();

  protected readonly showCompose = signal<boolean>(false);
  protected readonly replyMode = signal<ComposerMode>('Reply');
  protected readonly showAudit = signal<boolean>(false);

  protected readonly ai = computed(() => {
    const r = this.row();
    if (!r) return null;
    return MAIL_AI_DRAFTS[r.message_id] ?? null;
  });

  protected readonly history = computed(() => {
    const r = this.row();
    if (!r) return EMPTY_HISTORY;
    return MAIL_THREAD_HISTORY[r.conversation_id] ?? EMPTY_HISTORY;
  });

  protected readonly collapsedHistory = computed(() => this.history().filter((m) => m.collapsed));

  protected readonly audit = computed(() => {
    const r = this.row();
    if (!r) return EMPTY_AUDIT;
    return MAIL_AUDIT[r.message_id] ?? EMPTY_AUDIT;
  });

  protected readonly notes = computed(() => {
    const r = this.row();
    if (!r) return EMPTY_NOTES;
    return MAIL_INTERNAL_NOTES[r.message_id] ?? EMPTY_NOTES;
  });

  protected readonly vendor = computed(() => {
    const r = this.row();
    if (!r) return null;
    return VENDORS.find((v) => v.vendor_id === r.vendor_id) ?? null;
  });

  protected readonly dateText = computed<string>(() => {
    const r = this.row();
    return r ? new Date(r.received_at).toUTCString() : '';
  });

  protected readonly seedBody = computed<string>(() =>
    this.replyMode() === 'AI draft' ? (this.ai()?.body_text ?? '') : '',
  );

  protected startReply(mode: ComposerMode): void {
    this.replyMode.set(mode);
    this.showCompose.set(true);
  }

  protected histTime(iso: string): string {
    return fmtMailTime(iso);
  }

  protected formatBytes(n: number): string {
    return fmtBytes(n);
  }

  protected attachIcon(mime: string, filename: string): string {
    if (mime.includes('pdf')) return 'file-text';
    if (filename.endsWith('.xlsx')) return 'file-spreadsheet';
    return 'file';
  }
}
