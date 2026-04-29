import { ChangeDetectionStrategy, Component, computed, input, output, signal } from '@angular/core';
import { Icon } from '../../ui/icon';
import { Mono } from '../../ui/mono';
import type { MailThread } from '../../data/mail';

export type ComposerMode = 'Reply' | 'Reply all' | 'Forward' | 'AI draft';

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
              style="flex:1; border:none; padding:4px 0; border-radius:0; background: transparent; font-size:12.5px;"
            />
          </div>
          <div class="flex items-center gap-3" style="font-size:12.5px;">
            <span class="muted" style="width:56px; text-align:right; font-size:11px;">Cc</span>
            <input
              [value]="ccAddr()"
              style="flex:1; border:none; padding:4px 0; border-radius:0; background: transparent; font-size:12.5px;"
            />
          </div>
          <div class="flex items-center gap-3" style="font-size:12.5px;">
            <span class="muted" style="width:56px; text-align:right; font-size:11px;">Bcc</span>
            <input
              value=""
              style="flex:1; border:none; padding:4px 0; border-radius:0; background: transparent; font-size:12.5px;"
            />
          </div>
          <div class="flex items-center gap-3" style="font-size:12.5px;">
            <span class="muted" style="width:56px; text-align:right; font-size:11px;">Subject</span>
            <input
              [value]="subject()"
              style="flex:1; border:none; padding:4px 0; border-radius:0; background: transparent; font-size:12.5px;"
            />
          </div>
        </div>

        <div class="flex items-center gap-1 px-4 py-1.5 border-b hairline">
          @for (i of toolbarIcons; track i) {
            <button class="btn btn-ghost" style="padding:4px 6px;">
              <vq-icon [name]="i" [size]="12" />
            </button>
          }
          <div style="width:1px; height:18px; background: var(--line); margin: 0 4px;"></div>
          <button class="btn btn-ghost" style="padding:4px 8px; font-size:11.5px;">
            <vq-icon name="paperclip" [size]="12" /> Attach
          </button>
          <button class="btn btn-ghost" style="padding:4px 8px; font-size:11.5px;">
            <vq-icon name="file-text" [size]="12" /> Template
          </button>
        </div>

        <textarea
          [value]="body()"
          (input)="body.set(text($event))"
          [placeholder]="placeholder()"
          style="width:100%; min-height:200px; font-size:13px; line-height:1.6; border:none; border-radius:0; padding:16px; resize: vertical;"
        ></textarea>

        <div
          class="flex items-center gap-2 px-4 py-2.5 border-t hairline"
          style="background: var(--bg);"
        >
          <button class="btn btn-accent">
            <vq-icon name="send" [size]="13" /> Send via Microsoft Graph
          </button>
          <button class="btn">
            <vq-icon name="check-check" [size]="13" /> Send & resolve query
          </button>
          <button class="btn">
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
      </div>
    </div>
  `,
})
export class InlineComposer {
  readonly mode = input.required<ComposerMode>();
  readonly row = input.required<MailThread>();
  readonly seedBody = input<string>('');
  readonly closed = output<void>();

  protected readonly toolbarIcons = TOOLBAR_ICONS;
  protected readonly body = signal<string>('');
  protected readonly resolveOnSend = signal<boolean>(false);

  constructor() {
    queueMicrotask(() => this.body.set(this.seedBody()));
  }

  protected readonly toAddr = computed<string>(() =>
    this.mode() === 'Forward' ? '' : this.row().from_address,
  );
  protected readonly ccAddr = computed<string>(() => this.row().cc_addresses.join(', '));
  protected readonly subject = computed<string>(() => {
    const prefix = this.mode() === 'Forward' ? 'Fwd: ' : 'Re: ';
    const stripped = this.row().subject.replace(/^(Re:|Fwd:)\s*/i, '');
    return prefix + stripped;
  });

  protected readonly placeholder = computed<string>(
    () => `Type your ${this.mode().toLowerCase()}…`,
  );

  protected text(e: Event): string {
    return (e.target as HTMLTextAreaElement).value;
  }

  protected checkbox(e: Event): boolean {
    return (e.target as HTMLInputElement).checked;
  }
}
