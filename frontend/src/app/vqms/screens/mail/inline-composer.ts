import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { Icon } from '../../ui/icon';
import { Mono } from '../../ui/mono';
import {
  AdminEmailApi,
  type AdminSendResultDto,
} from '../../services/admin-email.api';
import type { MailThread } from '../../data/mail';

export type ComposerMode = 'Reply' | 'Reply all' | 'Forward' | 'AI draft';

type SendStatus = 'idle' | 'sending' | 'sent' | 'error';

const TOOLBAR_ICONS: readonly string[] = [
  'bold',
  'italic',
  'underline',
  'list',
  'list-ordered',
  'link',
  'code',
  'quote',
];

@Component({
  selector: 'vq-mail-inline-composer',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Icon, Mono],
  template: `
    <div class="px-6 pb-6 fade-up">
      <div class="panel" style="border-radius:4px; border-color: var(--line-strong);">
        <div
          class="flex items-center gap-2 px-4 py-2.5 border-b hairline"
          style="background: var(--bg);"
        >
          <vq-icon name="pen-line" [size]="13" cssClass="text-accent" />
          <span class="ink" style="font-size:12.5px; font-weight:600;">{{ mode() }}</span>
          <vq-mono cssClass="muted" [size]="10.5">
            · conversationId preserved · POST /admin/email/queries/{{ row().query_id }}/reply
          </vq-mono>
          <span class="flex-1"></span>
          <button class="btn btn-ghost" (click)="closed.emit()">
            <vq-icon name="x" [size]="13" />
          </button>
        </div>

        <div class="px-4 py-2 border-b hairline space-y-1">
          <div class="flex items-center gap-3" style="font-size:12.5px;">
            <span class="muted" style="width:56px; text-align:right; font-size:11px;">To</span>
            <input
              [value]="toAddr()"
              (input)="toAddr.set(input($event))"
              style="flex:1; border:none; padding:4px 0; border-radius:0; background: transparent; font-size:12.5px;"
            />
          </div>
          <div class="flex items-center gap-3" style="font-size:12.5px;">
            <span class="muted" style="width:56px; text-align:right; font-size:11px;">Cc</span>
            <input
              [value]="ccAddr()"
              (input)="ccAddr.set(input($event))"
              style="flex:1; border:none; padding:4px 0; border-radius:0; background: transparent; font-size:12.5px;"
            />
          </div>
          <div class="flex items-center gap-3" style="font-size:12.5px;">
            <span class="muted" style="width:56px; text-align:right; font-size:11px;">Bcc</span>
            <input
              [value]="bccAddr()"
              (input)="bccAddr.set(input($event))"
              style="flex:1; border:none; padding:4px 0; border-radius:0; background: transparent; font-size:12.5px;"
            />
          </div>
          <div class="flex items-center gap-3" style="font-size:12.5px;">
            <span class="muted" style="width:56px; text-align:right; font-size:11px;">Subject</span>
            <input
              [value]="subject()"
              (input)="subject.set(input($event))"
              style="flex:1; border:none; padding:4px 0; border-radius:0; background: transparent; font-size:12.5px;"
            />
          </div>
        </div>

        <div class="flex items-center gap-1 px-4 py-1.5 border-b hairline">
          @for (i of toolbarIcons; track i) {
            <button class="btn btn-ghost" style="padding:4px 6px;" type="button">
              <vq-icon [name]="i" [size]="12" />
            </button>
          }
          <div style="width:1px; height:18px; background: var(--line); margin: 0 4px;"></div>
          <button class="btn btn-ghost" style="padding:4px 8px; font-size:11.5px;" type="button" (click)="filePicker.click()">
            <vq-icon name="paperclip" [size]="12" /> Attach
          </button>
          <input
            #filePicker
            type="file"
            multiple
            (change)="onFiles($event)"
            style="display:none;"
          />
          <button class="btn btn-ghost" style="padding:4px 8px; font-size:11.5px;" type="button">
            <vq-icon name="file-text" [size]="12" /> Template
          </button>
          @if (files().length > 0) {
            <span class="muted ml-2" style="font-size:11px;">
              <vq-icon name="paperclip" [size]="10" /> {{ files().length }} file{{ files().length === 1 ? '' : 's' }}
              ({{ totalKb() }} KB)
            </span>
            <button class="btn btn-ghost" style="padding:2px 6px;" type="button" (click)="clearFiles()">
              <vq-icon name="x" [size]="11" />
            </button>
          }
        </div>

        <textarea
          [value]="body()"
          (input)="body.set(text($event))"
          [placeholder]="placeholder()"
          [disabled]="status() === 'sending'"
          style="width:100%; min-height:200px; font-size:13px; line-height:1.6; border:none; border-radius:0; padding:16px; resize: vertical;"
        ></textarea>

        <div
          class="flex items-center gap-2 px-4 py-2.5 border-t hairline"
          style="background: var(--bg);"
        >
          <button
            class="btn btn-accent"
            type="button"
            (click)="send(false)"
            [disabled]="!canSend()"
          >
            @if (status() === 'sending') {
              <vq-icon name="rotate-cw" [size]="13" /> Sending…
            } @else {
              <vq-icon name="send" [size]="13" /> Send via Microsoft Graph
            }
          </button>
          <button class="btn" type="button" (click)="send(true)" [disabled]="!canSend()">
            <vq-icon name="check-check" [size]="13" /> Send & resolve query
          </button>
          <button class="btn" type="button" [disabled]="status() === 'sending'">
            <vq-icon name="save" [size]="13" /> Save draft
          </button>
          <span class="flex-1"></span>
          <label class="flex items-center gap-2 muted" style="font-size:11.5px;">
            <input
              type="checkbox"
              [checked]="resolveOnSend()"
              (change)="resolveOnSend.set(checkbox($event))"
              style="accent-color: var(--accent);"
            />
            mark <vq-mono [size]="10.5">{{ row().query_id }}</vq-mono> resolved
          </label>
        </div>

        @if (status() === 'sent') {
          <div
            class="px-4 py-2 border-t hairline flex items-center gap-2 fade-up"
            style="background: color-mix(in oklch, var(--ok) 8%, var(--panel)); color: var(--ok); font-size:12px;"
          >
            <vq-icon name="check-circle" [size]="13" />
            Sent
            @if (lastResult()?.idempotent_replay) {
              <span class="muted" style="font-size:11px;">(idempotent replay — original send returned)</span>
            }
            @if (lastResult()?.outbound_id; as oid) {
              <vq-mono cssClass="ml-auto muted" [size]="10.5">{{ oid }}</vq-mono>
            }
          </div>
        } @else if (status() === 'error') {
          <div
            class="px-4 py-2 border-t hairline flex items-center gap-2 fade-up"
            style="background: color-mix(in oklch, var(--bad) 8%, var(--panel)); color: var(--bad); font-size:12px;"
          >
            <vq-icon name="alert-circle" [size]="13" />
            {{ error() }}
            <button class="btn btn-ghost ml-auto" type="button" (click)="status.set('idle')">
              <vq-icon name="x" [size]="11" />
            </button>
          </div>
        }
      </div>
    </div>
  `,
})
export class InlineComposer {
  readonly mode = input.required<ComposerMode>();
  readonly row = input.required<MailThread>();
  readonly seedBody = input<string>('');
  readonly closed = output<void>();
  readonly sent = output<AdminSendResultDto>();

  readonly #api = inject(AdminEmailApi);

  protected readonly toolbarIcons = TOOLBAR_ICONS;
  protected readonly body = signal<string>('');
  protected readonly resolveOnSend = signal<boolean>(false);
  protected readonly toAddr = signal<string>('');
  protected readonly ccAddr = signal<string>('');
  protected readonly bccAddr = signal<string>('');
  protected readonly subject = signal<string>('');
  protected readonly files = signal<readonly File[]>([]);

  protected readonly status = signal<SendStatus>('idle');
  protected readonly error = signal<string>('');
  protected readonly lastResult = signal<AdminSendResultDto | null>(null);

  protected readonly placeholder = computed<string>(
    () => `Type your ${this.mode().toLowerCase()}…`,
  );
  protected readonly canSend = computed<boolean>(
    () =>
      this.status() !== 'sending' &&
      this.body().trim().length > 0 &&
      this.toAddr().trim().length > 0,
  );
  protected readonly totalKb = computed<number>(() =>
    Math.round(this.files().reduce((acc, f) => acc + f.size, 0) / 1024),
  );

  // Seed defaults once the @Input signals settle. Using queueMicrotask
  // keeps us out of a binding-time write — Angular forbids signal writes
  // synchronously inside an input's first read.
  constructor() {
    queueMicrotask(() => {
      this.body.set(this.seedBody());
      this.toAddr.set(this.mode() === 'Forward' ? '' : this.row().from_address);
      this.ccAddr.set(this.row().cc_addresses.join(', '));
      const prefix = this.mode() === 'Forward' ? 'Fwd: ' : 'Re: ';
      const stripped = this.row().subject.replace(/^(Re:|Fwd:)\s*/i, '');
      this.subject.set(prefix + stripped);
    });
  }

  protected text(e: Event): string {
    return (e.target as HTMLTextAreaElement).value;
  }

  protected input(e: Event): string {
    return (e.target as HTMLInputElement).value;
  }

  protected checkbox(e: Event): boolean {
    return (e.target as HTMLInputElement).checked;
  }

  protected onFiles(e: Event): void {
    const input = e.target as HTMLInputElement;
    if (!input.files) return;
    this.files.set([...this.files(), ...Array.from(input.files)]);
    // Allow re-selecting the same file later — input keeps its value
    // otherwise and the change event won't fire.
    input.value = '';
  }

  protected clearFiles(): void {
    this.files.set([]);
  }

  /**
   * Wraps the textarea content in a minimal HTML envelope before
   * posting. The backend stores body_html verbatim, so wrapping in
   * <p>…</p> keeps newlines as paragraph breaks in Outlook.
   */
  protected async send(alsoResolve: boolean): Promise<void> {
    if (!this.canSend()) return;
    if (alsoResolve) this.resolveOnSend.set(true);

    this.status.set('sending');
    this.error.set('');

    const bodyHtml = this.toHtml(this.body());

    try {
      const result = await firstValueFrom(
        this.#api.replyToQuery({
          queryId: this.row().query_id,
          bodyHtml,
          cc: this.ccAddr().trim() || undefined,
          bcc: this.bccAddr().trim() || undefined,
          // Only override "to" if the user changed it from the default
          // (the backend defaults to the original sender when omitted).
          toOverride:
            this.toAddr().trim() === this.row().from_address.trim()
              ? undefined
              : this.toAddr().trim(),
          files: this.files(),
          // Idempotency token — re-clicking Send within a session reuses
          // the same id so a flaky network doesn't double-send.
          requestId: this.#requestId(),
        }),
      );
      this.lastResult.set(result);
      this.status.set('sent');
      this.sent.emit(result);
    } catch (err: unknown) {
      this.status.set('error');
      this.error.set(this.#humanize(err));
    }
  }

  // Stable per-instance request id so a Send retry (after error) is
  // idempotent. New composer = new id.
  readonly #requestIdValue = `vqms-ui-${crypto.randomUUID?.() ?? Date.now()}`;
  #requestId(): string {
    return this.#requestIdValue;
  }

  // Plaintext → minimal HTML so newlines become paragraph breaks.
  // Escapes HTML special characters first to avoid injection from
  // pasted content — body_html is sent through Microsoft Graph as-is.
  private toHtml(plain: string): string {
    const escaped = plain
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
    const paragraphs = escaped
      .split(/\n{2,}/)
      .map((p) => `<p>${p.replace(/\n/g, '<br>')}</p>`)
      .join('');
    return paragraphs || '<p></p>';
  }

  #humanize(err: unknown): string {
    const e = err as { status?: number; error?: { detail?: string }; message?: string };
    if (e?.status === 0) return 'Cannot reach the API server.';
    if (e?.status === 401) return 'Session expired — please sign in again.';
    if (e?.status === 403) return 'Admin role required.';
    if (e?.status === 404) return e?.error?.detail ?? 'Query thread not found.';
    if (e?.status === 409) return 'Idempotency conflict — payload differs from previous send.';
    if (e?.status === 422) return e?.error?.detail ?? 'Invalid attachment or recipient.';
    if (e?.status === 502) return 'Microsoft Graph rejected the send — try again.';
    if (e?.error?.detail) return e.error.detail;
    return e?.message ?? 'Send failed.';
  }
}
