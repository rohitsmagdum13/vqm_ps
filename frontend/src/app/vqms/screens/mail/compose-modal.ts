import { ChangeDetectionStrategy, Component, computed, input, output, signal } from '@angular/core';
import { Icon } from '../../ui/icon';
import { Mono } from '../../ui/mono';
import { Avatar } from '../../ui/avatar';
import { CONTACTS, VENDORS } from '../../data/mock-data';
import { MAIL_TEMPLATES } from '../../data/mail';
import { QueriesStore } from '../../services/queries.store';
import { inject } from '@angular/core';

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
                (change)="vendorId.set(input($event))"
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
                @for (c of contacts(); track c.email; let i = $index) {
                  <label
                    class="flex items-center gap-2 panel px-3 py-2 cursor-pointer"
                    style="border-radius:4px;"
                  >
                    <input
                      type="checkbox"
                      [checked]="i === 0"
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
                style="width:100%; min-height:220px; font-size:13px; line-height:1.6;"
                placeholder="Compose your message…"
              ></textarea>
            </div>

            <div>
              <div class="muted uppercase tracking-wider mb-1.5" style="font-size:10px; font-weight:600;">
                Attachments
              </div>
              <div
                class="panel px-4 py-6 text-center"
                style="border-radius:4px; border-style: dashed; background: var(--bg);"
              >
                <vq-icon name="upload-cloud" [size]="20" cssClass="muted" />
                <div class="ink-2 mt-1" style="font-size:12.5px;">Drop files or click to upload</div>
                <vq-mono cssClass="muted" [size]="10.5"
                  >uploaded to Amazon S3 · sent via Microsoft Graph</vq-mono
                >
              </div>
            </div>
          </div>

          <div
            class="border-t hairline px-6 py-3 flex items-center gap-2 sticky bottom-0"
            style="background: var(--panel);"
          >
            <button class="btn btn-accent">
              <vq-icon name="send" [size]="13" /> Send via Microsoft Graph
            </button>
            <button class="btn">
              <vq-icon name="save" [size]="13" /> Save draft
            </button>
            <span class="flex-1"></span>
            <button class="btn btn-ghost" (click)="closed.emit()">Cancel</button>
          </div>
        </div>
      </div>
    }
  `,
})
export class ComposeModal {
  readonly open = input.required<boolean>();
  readonly closed = output<void>();

  readonly #queries = inject(QueriesStore);

  protected readonly vendors = VENDORS;
  protected readonly templates = MAIL_TEMPLATES;

  protected readonly vendorId = signal<string>('V-001');
  protected readonly linkQuery = signal<string>('none');
  protected readonly template = signal<string>('none');
  protected readonly subject = signal<string>('');
  protected readonly body = signal<string>('');

  protected readonly vendor = computed(() =>
    VENDORS.find((v) => v.vendor_id === this.vendorId()) ?? null,
  );

  protected readonly contacts = computed(() => CONTACTS[this.vendorId()] ?? []);

  protected readonly vendorQueries = computed(() =>
    this.#queries.list().filter((q) => q.vendor_id === this.vendorId()).slice(0, 8),
  );

  protected input(e: Event): string {
    return (e.target as HTMLInputElement | HTMLSelectElement).value;
  }

  protected text(e: Event): string {
    return (e.target as HTMLTextAreaElement).value;
  }
}
