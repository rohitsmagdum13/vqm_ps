import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  computed,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { Router } from '@angular/router';
import { Icon } from '../ui/icon';
import { Mono } from '../ui/mono';
import { Avatar } from '../ui/avatar';
import { Tier } from '../ui/tier';
import { Status } from '../ui/status';
import { Empty } from '../ui/empty';
import { Logo } from '../ui/logo';
import { Drawer } from '../ui/drawer';
import { SectionHead } from '../ui/section-head';
import { EndpointsButton } from '../ui/endpoints-button';
import { EndpointsDrawer } from '../ui/endpoints-drawer';
import { ENDPOINTS_PORTAL } from '../data/endpoints';
import { relativeTime } from '../data/mock-data';
import type {
  BackendPriority,
  BackendQueryType,
  QuerySubmissionDto,
} from '../services/portal-queries.api';
import { PortalKpisStore } from '../services/portal-kpis.store';
import { PortalQueriesStore } from '../services/portal-queries.store';
import { SessionService } from '../services/session.service';

type Tab = 'queries' | 'compose' | 'invoices' | 'contracts' | 'profile';
type SubmitMode = 'idle' | 'submitting' | 'success' | 'error';

interface IntentOption {
  readonly k: string;
  readonly l: string;
  readonly icon: string;
  readonly type: BackendQueryType;
}

/**
 * The portal's friendly 6-button picker maps to the 12 official
 * VQMS query types (`models/query.py:QUERY_TYPES`). The mapping
 * picks the closest match per category; "Other" falls through to
 * GENERAL_INQUIRY.
 */
const INTENTS: readonly IntentOption[] = [
  { k: 'INVOICE_DISPUTE', l: 'Invoice / payment', icon: 'receipt', type: 'INVOICE_PAYMENT' },
  { k: 'CONTRACT', l: 'Contract / SOW', icon: 'file-text', type: 'CONTRACT_QUERY' },
  { k: 'BANKING', l: 'Banking change', icon: 'credit-card', type: 'INVOICE_PAYMENT' },
  { k: 'TAX', l: 'Tax / W-9 / W-8', icon: 'landmark', type: 'COMPLIANCE_AUDIT' },
  { k: 'ONBOARDING', l: 'Onboarding', icon: 'user-plus', type: 'ONBOARDING' },
  { k: 'OTHER', l: 'Something else', icon: 'help-circle', type: 'GENERAL_INQUIRY' },
];

const PRIORITIES: readonly BackendPriority[] = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'];

const INVOICES: readonly {
  id: string;
  amt: number;
  issued: string;
  due: string;
  status: string;
  note?: string;
}[] = [
  {
    id: 'INV-88241',
    amt: 14750.0,
    issued: '2026-04-01',
    due: '2026-05-01',
    status: 'DRAFTING',
    note: 'Short paid · in dispute',
  },
  { id: 'INV-87104', amt: 8420.0, issued: '2026-03-15', due: '2026-04-15', status: 'RESOLVED' },
  { id: 'INV-86012', amt: 22100.0, issued: '2026-02-28', due: '2026-03-30', status: 'RESOLVED' },
  { id: 'INV-85006', amt: 4800.0, issued: '2026-02-01', due: '2026-03-03', status: 'RESOLVED' },
];

const VENDOR_CONTRACTS: readonly { id: string; title: string; value: number; term: string }[] = [
  {
    id: 'MSA-2024-001',
    title: 'Master Services Agreement',
    value: 480_000,
    term: '2024-01-04 → 2027-01-04',
  },
  {
    id: 'SOW-2026-014',
    title: 'Q2 2026 Statement of Work',
    value: 124_000,
    term: '2026-04-01 → 2026-06-30',
  },
];

const MAX_FILES = 10;
const MAX_TOTAL_BYTES = 25 * 1024 * 1024;

@Component({
  selector: 'vq-portal-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Icon, Mono, Avatar, Tier, Status, Empty, Logo, Drawer, SectionHead, EndpointsButton, EndpointsDrawer],
  template: `
    <div class="min-h-screen flex flex-col" style="background: var(--bg);">
      <header class="border-b hairline px-6 py-3" style="background: var(--panel);">
        <div class="max-w-[1280px] mx-auto flex items-center justify-between">
          <div class="flex items-center gap-3">
            <vq-logo [size]="24" />
            <div>
              <div class="ink" style="font-size:14px; font-weight:600; letter-spacing:-.01em;">VQMS Vendor Portal</div>
              <div class="muted" style="font-size:11px;">Hexaware Technologies · Vendor self-service</div>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <span class="chip">
              <vq-tier tier="PLATINUM" />
              <vq-mono cssClass="ml-1">{{ vendorId() }}</vq-mono>
            </span>
            <span class="ink-2" style="font-size:13px;">{{ vendorName() }}</span>
            <vq-avatar [name]="vendorName() || 'Vendor'" [size]="28" />
            <vq-endpoints-button (clicked)="endpointsOpen.set(true)" />
            <button class="btn btn-ghost" (click)="signOut()" title="Sign out">
              <vq-icon name="log-out" [size]="13" />
            </button>
          </div>
        </div>
      </header>

      <vq-endpoints-drawer
        [open]="endpointsOpen()"
        title="Vendor portal · backend contract"
        subtitle="src/api/routes/portal.py · vendor-scoped JWT"
        [endpoints]="endpoints"
        role="Vendor"
        (closed)="endpointsOpen.set(false)"
      />

      <div class="border-b hairline" style="background: var(--ink); color: var(--bg);">
        <div class="max-w-[1280px] mx-auto px-6 py-6 grid grid-cols-12 gap-4 items-center">
          <div class="col-span-7">
            <div class="mono" style="font-size:10.5px; opacity:.55; letter-spacing:.1em; text-transform:uppercase;">
              Welcome back
            </div>
            <div style="font-size:26px; font-weight:600; letter-spacing:-.02em; margin-top:4px;">
              {{ firstName() }}, you have
              <span style="color: var(--accent);">{{ kpis().open_queries }} open queries</span>.
            </div>
            <div style="font-size:12.5px; opacity:.7; margin-top:6px;">
              We typically respond within 4 hours during business days. Track status anytime —
              every reply is logged here and on email.
              @if (kpisError(); as err) {
                <span style="color: var(--accent); margin-left:6px;">· {{ err }}</span>
              }
            </div>
          </div>
          <div class="col-span-5 grid grid-cols-3 gap-3">
            <div
              style="background: rgba(255,255,255,.06); border: 1px solid rgba(255,255,255,.1); border-radius: 4px; padding: 12px 14px;"
            >
              <div class="mono" style="font-size:22px; font-weight:600; color: var(--bg); line-height:1;">
                {{ kpis().total_queries }}
              </div>
              <div class="mono" style="font-size:10px; opacity:.55; letter-spacing:.06em; text-transform:uppercase; margin-top:6px;">
                Total
              </div>
            </div>
            <div
              style="background: rgba(255,255,255,.06); border: 1px solid rgba(255,255,255,.1); border-radius: 4px; padding: 12px 14px;"
            >
              <div class="mono" style="font-size:22px; font-weight:600; color: var(--ok); line-height:1;">
                {{ kpis().resolved_queries }}
              </div>
              <div class="mono" style="font-size:10px; opacity:.55; letter-spacing:.06em; text-transform:uppercase; margin-top:6px;">
                Resolved
              </div>
            </div>
            <div
              style="background: rgba(255,255,255,.06); border: 1px solid rgba(255,255,255,.1); border-radius: 4px; padding: 12px 14px;"
            >
              <div class="mono" style="font-size:22px; font-weight:600; color: var(--accent); line-height:1;">
                {{ kpis().open_queries }}
              </div>
              <div class="mono" style="font-size:10px; opacity:.55; letter-spacing:.06em; text-transform:uppercase; margin-top:6px;">
                Open
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="flex-1 max-w-[1280px] mx-auto w-full px-6 py-5">
        <div class="flex items-center justify-between mb-4">
          <div class="flex items-center gap-1">
            <span class="tab" [class.active]="tab() === 'queries'" (click)="tab.set('queries')">
              My queries <vq-mono cssClass="ml-1.5 muted">{{ myQueries().length }}</vq-mono>
            </span>
            <span
              class="tab"
              [class.active]="tab() === 'compose'"
              (click)="tab.set('compose'); openCompose()"
            >
              New query
            </span>
            <span class="tab" [class.active]="tab() === 'invoices'" (click)="tab.set('invoices')">
              Invoices <vq-mono cssClass="ml-1.5 muted">4</vq-mono>
            </span>
            <span class="tab" [class.active]="tab() === 'contracts'" (click)="tab.set('contracts')">
              Contracts <vq-mono cssClass="ml-1.5 muted">2</vq-mono>
            </span>
            <span class="tab" [class.active]="tab() === 'profile'" (click)="tab.set('profile')">
              Profile
            </span>
          </div>
          <div class="flex items-center gap-2">
            @if (queriesStatus() === 'live') {
              <span class="chip" style="color: var(--ok); border-color: var(--ok);">
                <vq-icon name="check-circle" [size]="10" /> Live
              </span>
            }
            @if (queriesStatus() === 'loading') {
              <span class="chip"><vq-icon name="rotate-cw" [size]="10" /> Loading…</span>
            }
            @if (queriesStatus() === 'error') {
              <span class="chip" style="color: var(--bad); border-color: var(--bad);" [title]="queriesError() ?? ''">
                <vq-icon name="alert-circle" [size]="10" /> {{ queriesError() }}
              </span>
            }
            <button class="btn" (click)="refresh()" [disabled]="queriesStatus() === 'loading'">
              <vq-icon name="rotate-cw" [size]="13" /> Refresh
            </button>
            <button class="btn btn-accent" (click)="openCompose()">
              <vq-icon name="plus" [size]="13" /> New query
            </button>
          </div>
        </div>

        @if (tab() === 'queries') {
          <div class="grid grid-cols-12 gap-3">
            <div class="col-span-12 panel" style="border-radius:4px; overflow:hidden;">
              <table class="vqms-table">
                <thead>
                  <tr>
                    <th>Reference</th><th>Subject</th><th>Status</th>
                    <th>Last update</th><th style="text-align:right">Submitted</th>
                  </tr>
                </thead>
                <tbody>
                  @for (q of myQueries(); track q.query_id) {
                    <tr>
                      <td><vq-mono [color]="'var(--ink)'" [weight]="500">{{ q.query_id }}</vq-mono></td>
                      <td>
                        <div class="ink-2" style="font-size:13px;">{{ q.subject }}</div>
                        <div class="muted mt-0.5" style="font-size:11px;">{{ q.intent }}</div>
                      </td>
                      <td><vq-status [value]="q.status" /></td>
                      <td><vq-mono cssClass="muted">{{ relative(q.received_at) }}</vq-mono></td>
                      <td style="text-align:right;"><vq-mono cssClass="muted">{{ q.received_at.slice(0, 10) }}</vq-mono></td>
                    </tr>
                  }
                  @if (myQueries().length === 0) {
                    <tr><td colspan="5"><vq-empty title="No queries yet" desc="Submit a new query to get started." /></td></tr>
                  }
                </tbody>
              </table>
            </div>
          </div>
        }

        @if (tab() === 'invoices') {
          <div class="panel" style="border-radius:4px; overflow:hidden;">
            <table class="vqms-table">
              <thead>
                <tr><th>Invoice</th><th>Amount</th><th>Issued</th><th>Due</th><th>Status</th></tr>
              </thead>
              <tbody>
                @for (inv of invoices; track inv.id) {
                  <tr>
                    <td>
                      <vq-mono [color]="'var(--ink)'" [weight]="500">{{ inv.id }}</vq-mono>
                      @if (inv.note) {
                        <div class="muted" style="font-size:11px;">{{ inv.note }}</div>
                      }
                    </td>
                    <td><vq-mono>\${{ formatAmount(inv.amt) }}</vq-mono></td>
                    <td><vq-mono cssClass="muted">{{ inv.issued }}</vq-mono></td>
                    <td><vq-mono cssClass="muted">{{ inv.due }}</vq-mono></td>
                    <td>
                      @if (inv.status === 'RESOLVED') {
                        <span class="chip" style="color: var(--ok); border-color: var(--ok);">Paid</span>
                      } @else {
                        <vq-status [value]="inv.status" />
                      }
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        }

        @if (tab() === 'contracts') {
          <div class="grid grid-cols-2 gap-3">
            @for (c of contracts; track c.id) {
              <div class="panel p-5" style="border-radius:4px;">
                <div class="flex items-start justify-between mb-2">
                  <vq-mono [color]="'var(--ink)'" [weight]="600">{{ c.id }}</vq-mono>
                  <span class="chip" style="color: var(--ok); border-color: var(--ok);">Active</span>
                </div>
                <div class="ink" style="font-size:15px; font-weight:500;">{{ c.title }}</div>
                <div class="muted mt-1" style="font-size:12px;">{{ c.term }}</div>
                <div class="mt-3 pt-3 border-t hairline flex items-center justify-between">
                  <div class="flex flex-col">
                    <span class="muted uppercase" style="font-size:10px; letter-spacing:.04em;">Value</span>
                    <span class="ink mono" style="font-size:13px; font-weight:600;">\${{ c.value.toLocaleString() }}</span>
                  </div>
                  <button class="btn"><vq-icon name="download" [size]="12" /> Download PDF</button>
                </div>
              </div>
            }
          </div>
        }

        @if (tab() === 'profile') {
          <div class="grid grid-cols-12 gap-3">
            <div class="panel p-5 col-span-7" style="border-radius:4px;">
              <vq-section-head title="Company profile" desc="Your master record · synced to Hexaware Salesforce CRM" />
              <div class="grid grid-cols-2 gap-x-6 gap-y-3 mt-3" style="font-size:12.5px;">
                <div>
                  <div class="muted uppercase mb-0.5" style="font-size:9.5px; letter-spacing:.06em;">Legal name</div>
                  <div class="ink-2" style="font-size:12px;">{{ vendorName() }}</div>
                </div>
                <div>
                  <div class="muted uppercase mb-0.5" style="font-size:9.5px; letter-spacing:.06em;">Vendor ID</div>
                  <vq-mono [size]="12">{{ vendorId() }}</vq-mono>
                </div>
                <div>
                  <div class="muted uppercase mb-0.5" style="font-size:9.5px; letter-spacing:.06em;">Email</div>
                  <vq-mono [size]="12">{{ email() }}</vq-mono>
                </div>
                <div>
                  <div class="muted uppercase mb-0.5" style="font-size:9.5px; letter-spacing:.06em;">Tenant</div>
                  <div class="ink-2" style="font-size:12px;">{{ tenant() }}</div>
                </div>
              </div>
              <div class="mt-4 pt-4 border-t hairline">
                <div class="muted uppercase mb-2" style="font-size:10px; letter-spacing:.04em;">Banking on file</div>
                <div class="flex items-center gap-2">
                  <vq-mono cssClass="muted">Acct ending **** 4271 · Bank of America · ACH</vq-mono>
                  <span class="chip"><vq-icon name="lock" [size]="10" /> Verified Apr 12</span>
                </div>
                <div class="muted mt-2" style="font-size:11.5px;">
                  To change banking details, submit a query — verification protocol requires phone
                  callback to your authorized contact.
                </div>
              </div>
            </div>
            <div class="panel p-5 col-span-5" style="border-radius:4px;">
              <vq-section-head title="Quick actions" />
              <div class="flex flex-col gap-2">
                <button class="btn justify-start" (click)="openCompose()">
                  <vq-icon name="plus" [size]="13" /> Submit a new query
                </button>
                <button class="btn justify-start" disabled><vq-icon name="upload" [size]="13" /> Upload W-9 / W-8BEN</button>
                <button class="btn justify-start" disabled><vq-icon name="upload" [size]="13" /> Upload insurance certificate</button>
                <button class="btn justify-start" disabled><vq-icon name="users" [size]="13" /> Manage authorized contacts</button>
                <button class="btn justify-start" disabled><vq-icon name="key" [size]="13" /> Reset password</button>
              </div>
            </div>
          </div>
        }
      </div>

      <vq-drawer [open]="composing()" [width]="640" (closed)="closeCompose()">
        <div class="px-6 py-4 border-b hairline">
          <div class="flex items-center justify-between">
            <div>
              <div class="ink" style="font-size:16px; font-weight:600;">New query</div>
              <div class="muted mt-0.5" style="font-size:12px;">
                Posts to <vq-mono>POST /queries</vq-mono> with multipart attachments. We'll reply within your tier SLA.
              </div>
            </div>
            <button class="btn btn-ghost" (click)="closeCompose()" [disabled]="submitMode() === 'submitting'">
              <vq-icon name="x" [size]="14" />
            </button>
          </div>
        </div>
        <form class="px-6 py-5 flex flex-col gap-4" (submit)="submit($event)">
          <div>
            <div class="muted uppercase mb-1" style="font-size:10px; letter-spacing:.04em;">What can we help with?</div>
            <div class="grid grid-cols-2 gap-2">
              @for (o of intentOptions; track o.k) {
                <label
                  class="flex items-center gap-2 p-3 rounded cursor-pointer"
                  [style.border]="intent() === o.k ? '1px solid var(--accent)' : '1px solid var(--line)'"
                  [style.background]="intent() === o.k ? 'var(--accent-soft)' : 'transparent'"
                >
                  <input
                    type="radio"
                    [checked]="intent() === o.k"
                    (change)="intent.set(o.k)"
                    [disabled]="submitMode() === 'submitting'"
                    style="accent-color: var(--accent);"
                  />
                  <vq-icon [name]="o.icon" [size]="13" cssClass="muted" />
                  <span style="font-size:12.5px;">{{ o.l }}</span>
                </label>
              }
            </div>
          </div>

          <div class="grid grid-cols-2 gap-3">
            <div class="col-span-2">
              <div class="muted uppercase mb-1" style="font-size:10px; letter-spacing:.04em;">
                Subject <span style="color: var(--bad);">*</span>
                <span class="ml-1">({{ subject().length }}/500)</span>
              </div>
              <input
                class="w-full"
                placeholder="One line that summarizes your question"
                [value]="subject()"
                (input)="subject.set(input($event))"
                [disabled]="submitMode() === 'submitting'"
              />
            </div>
            <div>
              <div class="muted uppercase mb-1" style="font-size:10px; letter-spacing:.04em;">Priority</div>
              <select
                class="w-full"
                [value]="priority()"
                (change)="setPriority(input($event))"
                [disabled]="submitMode() === 'submitting'"
              >
                @for (p of priorities; track p) {
                  <option>{{ p }}</option>
                }
              </select>
            </div>
            <div>
              <div class="muted uppercase mb-1" style="font-size:10px; letter-spacing:.04em;">Reference (optional)</div>
              <input
                class="w-full"
                placeholder="PO, invoice, or contract number"
                [value]="reference()"
                (input)="reference.set(input($event))"
                [disabled]="submitMode() === 'submitting'"
              />
            </div>
          </div>

          <div>
            <div class="muted uppercase mb-1" style="font-size:10px; letter-spacing:.04em;">
              Details <span style="color: var(--bad);">*</span>
              <span class="ml-1">({{ description().length }}/5000)</span>
            </div>
            <textarea
              class="w-full"
              style="min-height:140px; font-family:inherit; font-size:13px; line-height:1.55;"
              placeholder="Describe your question. Attach any relevant files below."
              [value]="description()"
              (input)="description.set(textareaInput($event))"
              [disabled]="submitMode() === 'submitting'"
            ></textarea>
          </div>

          <div>
            <div class="muted uppercase mb-1" style="font-size:10px; letter-spacing:.04em;">
              Attachments <span class="ml-1">({{ files().length }}/{{ maxFiles }})</span>
            </div>
            <input
              #fileInput
              type="file"
              multiple
              accept=".pdf,.docx,.xlsx,.csv,.txt,.png,.jpg,.jpeg"
              (change)="onFilesPicked($event)"
              [disabled]="submitMode() === 'submitting'"
              style="display:none;"
            />
            <div
              class="rounded p-4 text-center cursor-pointer"
              style="border: 1px dashed var(--line-strong);"
              (click)="fileInput.click()"
            >
              <vq-icon name="paperclip" [size]="16" cssClass="muted mb-2" />
              <div class="ink-2" style="font-size:12.5px;">Drop files or click to browse</div>
              <div class="muted" style="font-size:11px;">
                PDF, DOCX, XLSX, CSV, TXT, PNG, JPG · max {{ maxFiles }} files / 25MB total
              </div>
            </div>
            @if (files().length > 0) {
              <div class="mt-2 flex flex-col gap-1">
                @for (f of files(); track f.name; let i = $index) {
                  <div
                    class="flex items-center justify-between px-3 py-2 rounded"
                    style="background: var(--bg); font-size: 12px;"
                  >
                    <span class="flex items-center gap-2">
                      <vq-icon name="paperclip" [size]="11" cssClass="muted" />
                      <span class="ink-2">{{ f.name }}</span>
                      <vq-mono cssClass="muted">{{ formatFileSize(f.size) }}</vq-mono>
                    </span>
                    <button
                      type="button"
                      class="btn btn-ghost"
                      (click)="removeFile(i)"
                      [disabled]="submitMode() === 'submitting'"
                    >
                      <vq-icon name="x" [size]="11" />
                    </button>
                  </div>
                }
              </div>
            }
          </div>

          @if (errorMsg()) {
            <div
              class="flex items-start gap-2 p-3 rounded"
              style="background: color-mix(in oklch, var(--bad) 8%, var(--panel)); border: 1px solid var(--bad); color: var(--bad); font-size: 12.5px;"
            >
              <vq-icon name="alert-circle" [size]="14" />
              <span>{{ errorMsg() }}</span>
            </div>
          }

          @if (submitMode() === 'success' && createdId()) {
            <div
              class="flex items-start gap-2 p-3 rounded"
              style="background: color-mix(in oklch, var(--ok) 8%, var(--panel)); border: 1px solid var(--ok); color: var(--ok); font-size: 12.5px;"
            >
              <vq-icon name="check-circle" [size]="14" />
              <span>Submitted as <vq-mono [color]="'var(--ok)'" [weight]="600">{{ createdId() }}</vq-mono>. Closing…</span>
            </div>
          }

          <div class="flex items-center justify-between pt-3 border-t hairline">
            <div class="muted" style="font-size:11.5px;">
              <vq-icon name="info" [size]="11" cssClass="inline-block mr-1" />
              Subject 5–500 chars · Description 10–5000 chars
            </div>
            <div class="flex items-center gap-2">
              <button type="button" class="btn" (click)="closeCompose()" [disabled]="submitMode() === 'submitting'">
                Cancel
              </button>
              <button type="submit" class="btn btn-accent" [disabled]="!canSubmit()">
                @if (submitMode() === 'submitting') {
                  <vq-icon name="rotate-cw" [size]="13" />
                  Submitting…
                } @else {
                  <vq-icon name="send" [size]="13" />
                  Submit query
                }
              </button>
            </div>
          </div>
        </form>
      </vq-drawer>
    </div>
  `,
})
export class PortalPage {
  readonly #session = inject(SessionService);
  readonly #router = inject(Router);
  readonly #queriesStore = inject(PortalQueriesStore);
  readonly #kpisStore = inject(PortalKpisStore);

  protected readonly fileInput = viewChild<ElementRef<HTMLInputElement>>('fileInput');

  protected readonly intentOptions = INTENTS;
  protected readonly priorities = PRIORITIES;
  protected readonly invoices = INVOICES;
  protected readonly contracts = VENDOR_CONTRACTS;
  protected readonly maxFiles = MAX_FILES;
  protected readonly endpointsOpen = signal(false);
  protected readonly endpoints = ENDPOINTS_PORTAL;

  protected readonly tab = signal<Tab>('queries');
  protected readonly composing = signal<boolean>(false);

  protected readonly intent = signal<string>('INVOICE_DISPUTE');
  protected readonly subject = signal<string>('');
  protected readonly description = signal<string>('');
  protected readonly reference = signal<string>('');
  protected readonly priority = signal<BackendPriority>('MEDIUM');
  protected readonly files = signal<readonly File[]>([]);

  protected readonly submitMode = signal<SubmitMode>('idle');
  protected readonly errorMsg = signal<string>('');
  protected readonly createdId = signal<string>('');

  protected readonly vendorId = computed<string>(() => this.#session.vendorId() ?? '—');
  protected readonly vendorName = computed<string>(
    () => this.#session.vendorName() ?? this.#session.userName(),
  );
  protected readonly email = computed<string>(() => this.#session.email());
  protected readonly tenant = computed<string>(
    () => this.#session.session().tenant ?? '—',
  );
  protected readonly firstName = computed<string>(
    () => this.vendorName().split(' ')[0] ?? this.vendorName(),
  );

  protected readonly myQueries = this.#queriesStore.list;
  protected readonly queriesStatus = this.#queriesStore.status;
  protected readonly queriesError = this.#queriesStore.error;
  protected readonly kpis = this.#kpisStore.kpis;
  protected readonly kpisError = this.#kpisStore.error;

  protected readonly canSubmit = computed<boolean>(() => {
    if (this.submitMode() === 'submitting') return false;
    const subj = this.subject().trim();
    const desc = this.description().trim();
    return subj.length >= 5 && subj.length <= 500 && desc.length >= 10 && desc.length <= 5000;
  });

  protected input(e: Event): string {
    return (e.target as HTMLInputElement | HTMLSelectElement).value;
  }

  protected setPriority(value: string): void {
    if (PRIORITIES.includes(value as BackendPriority)) {
      this.priority.set(value as BackendPriority);
    }
  }

  protected textareaInput(e: Event): string {
    return (e.target as HTMLTextAreaElement).value;
  }

  protected openCompose(): void {
    this.composing.set(true);
  }

  protected closeCompose(): void {
    if (this.submitMode() === 'submitting') return;
    this.composing.set(false);
    this.#resetForm();
    if (this.tab() === 'compose') this.tab.set('queries');
  }

  protected onFilesPicked(e: Event): void {
    const target = e.target as HTMLInputElement;
    const picked = Array.from(target.files ?? []);
    const merged = [...this.files(), ...picked].slice(0, MAX_FILES);
    this.files.set(merged);
    target.value = '';
  }

  protected removeFile(idx: number): void {
    const next = [...this.files()];
    next.splice(idx, 1);
    this.files.set(next);
  }

  protected formatFileSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  }

  protected async submit(e: Event): Promise<void> {
    e.preventDefault();
    if (!this.canSubmit()) return;

    const totalBytes = this.files().reduce((sum, f) => sum + f.size, 0);
    if (totalBytes > MAX_TOTAL_BYTES) {
      this.errorMsg.set('Total attachment size exceeds 25 MB.');
      this.submitMode.set('error');
      return;
    }

    const intentOption = this.intentOptions.find((o) => o.k === this.intent());
    if (!intentOption) {
      this.errorMsg.set('Pick a query category.');
      return;
    }

    const submission: QuerySubmissionDto = {
      query_type: intentOption.type,
      subject: this.subject().trim(),
      description: this.description().trim(),
      priority: this.priority(),
      reference_number: this.reference().trim() || null,
    };

    this.submitMode.set('submitting');
    this.errorMsg.set('');
    this.createdId.set('');

    try {
      const result = await this.#queriesStore.submit(submission, this.files());
      this.createdId.set(result.query_id);
      this.submitMode.set('success');
      void this.#kpisStore.refresh();
      // Brief pause so the operator sees the success banner.
      window.setTimeout(() => {
        this.composing.set(false);
        this.#resetForm();
        this.tab.set('queries');
      }, 1500);
    } catch (err: unknown) {
      this.errorMsg.set(err instanceof Error ? err.message : 'Submit failed.');
      this.submitMode.set('error');
    }
  }

  protected refresh(): void {
    void this.#queriesStore.refresh();
    void this.#kpisStore.refresh();
  }

  protected async signOut(): Promise<void> {
    await this.#session.signOutAsync();
    void this.#router.navigate(['/login']);
  }

  protected formatAmount(n: number): string {
    return n.toLocaleString(undefined, { minimumFractionDigits: 2 });
  }

  protected relative(iso: string): string {
    return relativeTime(iso);
  }

  #resetForm(): void {
    this.intent.set('INVOICE_DISPUTE');
    this.subject.set('');
    this.description.set('');
    this.reference.set('');
    this.priority.set('MEDIUM');
    this.files.set([]);
    this.submitMode.set('idle');
    this.errorMsg.set('');
    this.createdId.set('');
    const fi = this.fileInput();
    if (fi) fi.nativeElement.value = '';
  }
}
