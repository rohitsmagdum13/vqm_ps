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
import { Avatar } from '../../ui/avatar';
import { CONTACTS, VENDORS } from '../../data/mock-data';
import { MAIL_TEMPLATES } from '../../data/mail';
import {
  AdminEmailApi,
  type AdminSendResultDto,
} from '../../services/admin-email.api';
import { QueriesStore } from '../../services/queries.store';

type SendStatus = 'idle' | 'sending' | 'sent' | 'error';

@Component({
  selector: 'vq-mail-compose-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Icon, Mono, Avatar],
  template: `
    @if (open()) {
      <div
        class="fixed inset-0 z-40"
        style="background: rgba(0,0,0,.32);"
        (click)="closed.emit()"
      >
        <div
          class="absolute right-0 top-0 bottom-0 panel fade-up overflow-auto"
          style="width:760px; max-width: 92vw; border-left: 1px solid var(--line-strong);"
          (click)="$event.stopPropagation()"
        >
          <div class="flex items-center justify-between px-6 py-4 border-b hairline">
            <div>
              <div class="ink" style="font-size:16px; font-weight:600;">New email</div>
              <vq-mono cssClass="muted" [size]="11"
                >POST /admin/email/send · X‑Request‑Id idempotency</vq-mono
              >
            </div>
            <button class="btn btn-ghost" (click)="closed.emit()">
              <vq-icon name="x" [size]="14" />
            </button>
          </div>

          <div class="px-6 py-4 space-y-4">
            <div>
              <div class="muted uppercase tracking-wider mb-1.5" style="font-size:10px; font-weight:600;">
                Vendor
              </div>
              <select
                [value]="vendorId()"
                (change)="onVendorChange(input($event))"
                style="width:100%;"
              >
                @for (v of vendors; track v.vendor_id) {
                  <option [value]="v.vendor_id">{{ v.vendor_id }} · {{ v.name }} · {{ v.tier }}</option>
                }
              </select>
              @if (vendor(); as v) {
                <div class="muted mt-1" style="font-size:11px;">
                  {{ v.category }} · {{ v.city }}, {{ v.country }} · SLA
                  <vq-mono>{{ v.sla_response_hours }}h/{{ v.sla_resolution_days }}d</vq-mono>
                </div>
              }
            </div>

            <div>
              <div class="muted uppercase tracking-wider mb-1.5" style="font-size:10px; font-weight:600;">
                Recipients
                <vq-mono cssClass="muted ml-1" [size]="10">from Vendor_Contact__c</vq-mono>
              </div>
              <div class="space-y-1.5">
                @for (c of contacts(); track c.email) {
                  <label
                    class="flex items-center gap-2 panel px-3 py-2 cursor-pointer"
                    style="border-radius:4px;"
                  >
                    <input
                      type="checkbox"
                      [checked]="selectedRecipients().has(c.email)"
                      (change)="toggleRecipient(c.email, checkbox($event))"
                      style="accent-color: var(--accent);"
                    />
                    <vq-avatar [name]="c.name" [size]="22" />
                    <div class="flex-1">
                      <div class="ink-2" style="font-size:12.5px; font-weight:500;">{{ c.name }}</div>
                      <vq-mono cssClass="muted" [size]="10.5"
                        >{{ c.email }} · {{ c.role }}</vq-mono
                      >
                    </div>
                  </label>
                }
                @if (contacts().length === 0) {
                  <div class="muted" style="font-size:12px;">
                    No contacts on file. Add one in Vendor 360.
                  </div>
                }
              </div>
              <div class="mt-2">
                <input
                  [value]="extraTo()"
                  (input)="extraTo.set(input($event))"
                  placeholder="Or add comma-separated email addresses…"
                  style="width:100%; font-size:12px;"
                />
              </div>
            </div>

            <div class="grid grid-cols-2 gap-3">
              <div>
                <div
                  class="muted uppercase tracking-wider mb-1.5"
                  style="font-size:10px; font-weight:600;"
                >
                  Link to query (optional)
                </div>
                <select
                  [value]="linkQuery()"
                  (change)="linkQuery.set(input($event))"
                  style="width:100%;"
                >
                  <option value="none">— None —</option>
                  @for (q of vendorQueries(); track q.query_id) {
                    <option [value]="q.query_id">
                      {{ q.query_id }} · {{ q.subject.slice(0, 50) }}
                    </option>
                  }
                </select>
              </div>
              <div>
                <div
                  class="muted uppercase tracking-wider mb-1.5"
                  style="font-size:10px; font-weight:600;"
                >
                  Template
                </div>
                <select
                  [value]="template()"
                  (change)="template.set(input($event))"
                  style="width:100%;"
                >
                  <option value="none">— None —</option>
                  @for (t of templates; track t.id) {
                    <option [value]="t.id">{{ t.category }} · {{ t.name }}</option>
                  }
                </select>
              </div>
            </div>

            <div>
              <div class="muted uppercase tracking-wider mb-1.5" style="font-size:10px; font-weight:600;">
                Subject
              </div>
              <input
                [value]="subject()"
                (input)="subject.set(input($event))"
                style="width:100%;"
                placeholder="e.g. Banking detail change — verification required"
              />
            </div>

            <div>
              <div class="muted uppercase tracking-wider mb-1.5" style="font-size:10px; font-weight:600;">
                Message
              </div>
              <textarea
                [value]="body()"
                (input)="body.set(text($event))"
                [disabled]="status() === 'sending'"
                style="width:100%; min-height:220px; font-size:13px; line-height:1.6;"
                placeholder="Compose your message…"
              ></textarea>
            </div>

            <div>
              <div class="muted uppercase tracking-wider mb-1.5" style="font-size:10px; font-weight:600;">
                Attachments
              </div>
              <div
                class="panel px-4 py-6 text-center cursor-pointer"
                style="border-radius:4px; border-style: dashed; background: var(--bg);"
                (click)="filePicker.click()"
              >
                <vq-icon name="upload-cloud" [size]="20" cssClass="muted" />
                <div class="ink-2 mt-1" style="font-size:12.5px;">
                  @if (files().length === 0) {
                    Drop files or click to upload
                  } @else {
                    <vq-mono>{{ files().length }}</vq-mono> file{{ files().length === 1 ? '' : 's' }}
                    selected · {{ totalKb() }} KB
                  }
                </div>
                <vq-mono cssClass="muted" [size]="10.5"
                  >uploaded to Amazon S3 · sent via Microsoft Graph</vq-mono
                >
              </div>
              <input
                #filePicker
                type="file"
                multiple
                (change)="onFiles($event)"
                style="display:none;"
              />
              @if (files().length > 0) {
                <button
                  class="btn btn-ghost mt-1"
                  type="button"
                  style="font-size:11px;"
                  (click)="clearFiles()"
                >
                  <vq-icon name="x" [size]="11" /> Clear attachments
                </button>
              }
            </div>

            @if (status() === 'sent') {
              <div
                class="px-4 py-2 fade-up flex items-center gap-2"
                style="background: color-mix(in oklch, var(--ok) 8%, var(--panel)); color: var(--ok); border-radius:4px; font-size:12px;"
              >
                <vq-icon name="check-circle" [size]="13" />
                Sent
                @if (lastResult()?.idempotent_replay) {
                  <span class="muted" style="font-size:11px;">(idempotent replay)</span>
                }
                @if (lastResult()?.outbound_id; as oid) {
                  <vq-mono cssClass="ml-auto muted" [size]="10.5">{{ oid }}</vq-mono>
                }
              </div>
            } @else if (status() === 'error') {
              <div
                class="px-4 py-2 fade-up flex items-center gap-2"
                style="background: color-mix(in oklch, var(--bad) 8%, var(--panel)); color: var(--bad); border-radius:4px; font-size:12px;"
              >
                <vq-icon name="alert-circle" [size]="13" />
                {{ error() }}
                <button
                  class="btn btn-ghost ml-auto"
                  type="button"
                  (click)="status.set('idle')"
                >
                  <vq-icon name="x" [size]="11" />
                </button>
              </div>
            }
          </div>

          <div
            class="border-t hairline px-6 py-3 flex items-center gap-2 sticky bottom-0"
            style="background: var(--panel);"
          >
            <button
              class="btn btn-accent"
              type="button"
              (click)="send()"
              [disabled]="!canSend()"
            >
              @if (status() === 'sending') {
                <vq-icon name="rotate-cw" [size]="13" /> Sending…
              } @else {
                <vq-icon name="send" [size]="13" /> Send via Microsoft Graph
              }
            </button>
            <button class="btn" type="button" [disabled]="status() === 'sending'">
              <vq-icon name="save" [size]="13" /> Save draft
            </button>
            <span class="flex-1"></span>
            <button class="btn btn-ghost" (click)="closed.emit()">
              {{ status() === 'sent' ? 'Close' : 'Cancel' }}
            </button>
          </div>
        </div>
      </div>
    }
  `,
})
export class ComposeModal {
  readonly open = input.required<boolean>();
  readonly closed = output<void>();
  readonly sent = output<AdminSendResultDto>();

  readonly #api = inject(AdminEmailApi);
  readonly #queries = inject(QueriesStore);

  protected readonly vendors = VENDORS;
  protected readonly templates = MAIL_TEMPLATES;

  protected readonly vendorId = signal<string>('V-001');
  protected readonly linkQuery = signal<string>('none');
  protected readonly template = signal<string>('none');
  protected readonly subject = signal<string>('');
  protected readonly body = signal<string>('');
  protected readonly extraTo = signal<string>('');
  protected readonly selectedRecipients = signal<ReadonlySet<string>>(
    new Set(CONTACTS['V-001']?.[0]?.email ? [CONTACTS['V-001']![0]!.email] : []),
  );
  protected readonly files = signal<readonly File[]>([]);

  protected readonly status = signal<SendStatus>('idle');
  protected readonly error = signal<string>('');
  protected readonly lastResult = signal<AdminSendResultDto | null>(null);

  protected readonly vendor = computed(() =>
    VENDORS.find((v) => v.vendor_id === this.vendorId()) ?? null,
  );
  protected readonly contacts = computed(() => CONTACTS[this.vendorId()] ?? []);
  protected readonly vendorQueries = computed(() =>
    this.#queries.list().filter((q) => q.vendor_id === this.vendorId()).slice(0, 8),
  );

  protected readonly recipientCount = computed<number>(() => {
    const fromContacts = this.selectedRecipients().size;
    const fromManual = this.extraTo()
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean).length;
    return fromContacts + fromManual;
  });

  protected readonly canSend = computed<boolean>(
    () =>
      this.status() !== 'sending' &&
      this.subject().trim().length > 0 &&
      this.body().trim().length > 0 &&
      this.recipientCount() > 0,
  );

  protected readonly totalKb = computed<number>(() =>
    Math.round(this.files().reduce((acc, f) => acc + f.size, 0) / 1024),
  );

  // Switching vendor pre-selects the first contact for convenience
  // and clears any manually-typed addresses (which were vendor-scoped).
  protected onVendorChange(id: string): void {
    this.vendorId.set(id);
    const first = (CONTACTS[id] ?? [])[0]?.email;
    this.selectedRecipients.set(new Set(first ? [first] : []));
    this.extraTo.set('');
  }

  protected toggleRecipient(email: string, on: boolean): void {
    const next = new Set(this.selectedRecipients());
    if (on) next.add(email);
    else next.delete(email);
    this.selectedRecipients.set(next);
  }

  protected onFiles(e: Event): void {
    const input = e.target as HTMLInputElement;
    if (!input.files) return;
    this.files.set([...this.files(), ...Array.from(input.files)]);
    input.value = '';
  }

  protected clearFiles(): void {
    this.files.set([]);
  }

  protected async send(): Promise<void> {
    if (!this.canSend()) return;

    const recipients = [
      ...this.selectedRecipients(),
      ...this.extraTo()
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean),
    ];

    this.status.set('sending');
    this.error.set('');

    try {
      const result = await firstValueFrom(
        this.#api.send({
          to: recipients.join(','),
          subject: this.subject(),
          bodyHtml: this.toHtml(this.body()),
          vendorId: this.vendorId(),
          queryId: this.linkQuery() === 'none' ? undefined : this.linkQuery(),
          files: this.files(),
          requestId: this.#requestIdValue,
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

  protected input(e: Event): string {
    return (e.target as HTMLInputElement | HTMLSelectElement).value;
  }

  protected text(e: Event): string {
    return (e.target as HTMLTextAreaElement).value;
  }

  protected checkbox(e: Event): boolean {
    return (e.target as HTMLInputElement).checked;
  }

  // Stable per-instance request id so a Send retry (after error) is
  // idempotent against the backend's `X-Request-Id` dedup. New modal
  // open = same instance = same id, so re-clicks during a transient
  // failure don't double-send.
  readonly #requestIdValue = `vqms-ui-${crypto.randomUUID?.() ?? Date.now()}`;

  // Plaintext → minimal HTML so newlines become paragraph breaks.
  // Escapes HTML special chars first to avoid injection from pasted
  // content — body_html is sent through Microsoft Graph as-is.
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
    if (e?.status === 400) return e?.error?.detail ?? 'At least one recipient is required.';
    if (e?.status === 401) return 'Session expired — please sign in again.';
    if (e?.status === 403) return 'Admin role required.';
    if (e?.status === 404) return e?.error?.detail ?? 'Linked query not found.';
    if (e?.status === 409) return 'Idempotency conflict — payload differs from previous send.';
    if (e?.status === 422) return e?.error?.detail ?? 'Invalid attachment or recipient.';
    if (e?.status === 502) return 'Microsoft Graph rejected the send — try again.';
    if (e?.error?.detail) return e.error.detail;
    return e?.message ?? 'Send failed.';
  }
}
