import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { Icon } from '../ui/icon';
import { Drawer } from '../ui/drawer';
import { VendorsStore } from '../services/vendors.store';
import type { VendorCreateRequestDto } from '../services/vendors.api';

type Mode = 'idle' | 'submitting' | 'error';

const TIERS: readonly string[] = ['Platinum', 'Gold', 'Silver', 'Bronze'];
const PAYMENT_TERMS: readonly string[] = ['Net-30', 'Net-45', 'Net-60', 'Net-90'];
const STATUSES: readonly string[] = ['Active', 'Inactive'];

interface FormState {
  readonly name: string;
  readonly website: string;
  readonly vendorTier: string;
  readonly category: string;
  readonly paymentTerms: string;
  readonly annualRevenue: string;
  readonly slaResponseHours: string;
  readonly slaResolutionDays: string;
  readonly vendorStatus: string;
  readonly onboardedDate: string;
  readonly billingCity: string;
  readonly billingState: string;
  readonly billingCountry: string;
}

const EMPTY: FormState = {
  name: '',
  website: '',
  vendorTier: 'Silver',
  category: '',
  paymentTerms: 'Net-30',
  annualRevenue: '',
  slaResponseHours: '',
  slaResolutionDays: '',
  vendorStatus: 'Active',
  onboardedDate: '',
  billingCity: '',
  billingState: '',
  billingCountry: '',
};

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

@Component({
  selector: 'vq-vendor-form-drawer',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Icon, Drawer],
  template: `
    <vq-drawer [open]="open()" [width]="640" (closed)="cancel()">
      <div class="px-6 py-4 border-b hairline">
        <div class="flex items-center justify-between">
          <div>
            <div class="ink" style="font-size:16px; font-weight:600;">New vendor</div>
            <div class="muted mt-0.5" style="font-size:12px;">
              Creates a Vendor_Account__c record in Salesforce. Vendor ID (V-XXX) is auto-generated.
            </div>
          </div>
          <button class="btn btn-ghost" (click)="cancel()">
            <vq-icon name="x" [size]="14" />
          </button>
        </div>
      </div>

      <form class="px-6 py-5 flex flex-col gap-4" (submit)="submit($event)">
        <div>
          <div class="muted uppercase mb-1" style="font-size:10px; letter-spacing:.04em;">
            Legal name <span style="color: var(--bad);">*</span>
          </div>
          <input
            class="w-full"
            placeholder="Cloudwave Hosting Inc."
            [value]="form().name"
            (input)="set('name', input($event))"
            [disabled]="mode() === 'submitting'"
          />
        </div>

        <div class="grid grid-cols-2 gap-3">
          <div>
            <div class="muted uppercase mb-1" style="font-size:10px; letter-spacing:.04em;">Website</div>
            <input
              class="w-full"
              placeholder="https://example.com"
              [value]="form().website"
              (input)="set('website', input($event))"
              [disabled]="mode() === 'submitting'"
            />
          </div>
          <div>
            <div class="muted uppercase mb-1" style="font-size:10px; letter-spacing:.04em;">Tier</div>
            <select
              class="w-full"
              [value]="form().vendorTier"
              (change)="set('vendorTier', input($event))"
              [disabled]="mode() === 'submitting'"
            >
              @for (t of tiers; track t) {
                <option>{{ t }}</option>
              }
            </select>
          </div>
        </div>

        <div class="grid grid-cols-2 gap-3">
          <div>
            <div class="muted uppercase mb-1" style="font-size:10px; letter-spacing:.04em;">Category</div>
            <input
              class="w-full"
              placeholder="IT Services"
              [value]="form().category"
              (input)="set('category', input($event))"
              [disabled]="mode() === 'submitting'"
            />
          </div>
          <div>
            <div class="muted uppercase mb-1" style="font-size:10px; letter-spacing:.04em;">Payment terms</div>
            <select
              class="w-full"
              [value]="form().paymentTerms"
              (change)="set('paymentTerms', input($event))"
              [disabled]="mode() === 'submitting'"
            >
              @for (p of paymentTermsOptions; track p) {
                <option>{{ p }}</option>
              }
            </select>
          </div>
        </div>

        <div class="grid grid-cols-3 gap-3">
          <div>
            <div class="muted uppercase mb-1" style="font-size:10px; letter-spacing:.04em;">Annual revenue</div>
            <input
              class="w-full"
              type="number"
              placeholder="5000000"
              [value]="form().annualRevenue"
              (input)="set('annualRevenue', input($event))"
              [disabled]="mode() === 'submitting'"
            />
          </div>
          <div>
            <div class="muted uppercase mb-1" style="font-size:10px; letter-spacing:.04em;">SLA response (h)</div>
            <input
              class="w-full"
              type="number"
              placeholder="4"
              [value]="form().slaResponseHours"
              (input)="set('slaResponseHours', input($event))"
              [disabled]="mode() === 'submitting'"
            />
          </div>
          <div>
            <div class="muted uppercase mb-1" style="font-size:10px; letter-spacing:.04em;">SLA resolution (d)</div>
            <input
              class="w-full"
              type="number"
              placeholder="3"
              [value]="form().slaResolutionDays"
              (input)="set('slaResolutionDays', input($event))"
              [disabled]="mode() === 'submitting'"
            />
          </div>
        </div>

        <div class="grid grid-cols-2 gap-3">
          <div>
            <div class="muted uppercase mb-1" style="font-size:10px; letter-spacing:.04em;">Status</div>
            <select
              class="w-full"
              [value]="form().vendorStatus"
              (change)="set('vendorStatus', input($event))"
              [disabled]="mode() === 'submitting'"
            >
              @for (s of statuses; track s) {
                <option>{{ s }}</option>
              }
            </select>
          </div>
          <div>
            <div class="muted uppercase mb-1" style="font-size:10px; letter-spacing:.04em;">
              Onboarded (YYYY-MM-DD)
            </div>
            <input
              class="w-full"
              placeholder="2026-04-29"
              [value]="form().onboardedDate"
              (input)="set('onboardedDate', input($event))"
              [disabled]="mode() === 'submitting'"
            />
          </div>
        </div>

        <div class="grid grid-cols-3 gap-3">
          <div>
            <div class="muted uppercase mb-1" style="font-size:10px; letter-spacing:.04em;">City</div>
            <input
              class="w-full"
              placeholder="Mumbai"
              [value]="form().billingCity"
              (input)="set('billingCity', input($event))"
              [disabled]="mode() === 'submitting'"
            />
          </div>
          <div>
            <div class="muted uppercase mb-1" style="font-size:10px; letter-spacing:.04em;">State</div>
            <input
              class="w-full"
              placeholder="Maharashtra"
              [value]="form().billingState"
              (input)="set('billingState', input($event))"
              [disabled]="mode() === 'submitting'"
            />
          </div>
          <div>
            <div class="muted uppercase mb-1" style="font-size:10px; letter-spacing:.04em;">Country</div>
            <input
              class="w-full"
              placeholder="India"
              [value]="form().billingCountry"
              (input)="set('billingCountry', input($event))"
              [disabled]="mode() === 'submitting'"
            />
          </div>
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

        <div class="flex items-center justify-between pt-3 border-t hairline">
          <div class="muted" style="font-size:11.5px;">
            <vq-icon name="info" [size]="11" cssClass="inline-block mr-1" />
            Required: Legal name. Vendor ID (V-XXX) is generated automatically.
          </div>
          <div class="flex items-center gap-2">
            <button type="button" class="btn" (click)="cancel()" [disabled]="mode() === 'submitting'">
              Cancel
            </button>
            <button type="submit" class="btn btn-accent" [disabled]="!canSubmit()">
              @if (mode() === 'submitting') {
                <vq-icon name="rotate-cw" [size]="13" />
                Creating…
              } @else {
                <vq-icon name="plus" [size]="13" />
                Create vendor
              }
            </button>
          </div>
        </div>
      </form>
    </vq-drawer>
  `,
})
export class VendorFormDrawer {
  readonly #store = inject(VendorsStore);

  readonly open = input.required<boolean>();
  readonly closed = output<void>();
  readonly created = output<string>();

  protected readonly tiers = TIERS;
  protected readonly paymentTermsOptions = PAYMENT_TERMS;
  protected readonly statuses = STATUSES;

  protected readonly form = signal<FormState>(EMPTY);
  protected readonly mode = signal<Mode>('idle');
  protected readonly errorMsg = signal<string>('');

  protected readonly canSubmit = computed<boolean>(
    () => this.mode() !== 'submitting' && this.form().name.trim().length > 0,
  );

  protected input(e: Event): string {
    return (e.target as HTMLInputElement | HTMLSelectElement).value;
  }

  protected set<K extends keyof FormState>(key: K, value: string): void {
    this.form.update((f) => ({ ...f, [key]: value }));
  }

  protected cancel(): void {
    if (this.mode() === 'submitting') return;
    this.#reset();
    this.closed.emit();
  }

  protected async submit(e: Event): Promise<void> {
    e.preventDefault();
    if (!this.canSubmit()) return;

    const f = this.form();
    if (f.onboardedDate && !DATE_RE.test(f.onboardedDate)) {
      this.errorMsg.set('Onboarded date must be YYYY-MM-DD.');
      return;
    }

    const payload = this.#buildPayload(f);

    this.mode.set('submitting');
    this.errorMsg.set('');

    try {
      await this.#store.create(payload);
      const created = this.#store.vendors().find((v) => v.name === payload.name);
      this.created.emit(created?.vendor_id ?? '');
      this.#reset();
      this.closed.emit();
    } catch (err: unknown) {
      this.errorMsg.set(err instanceof Error ? err.message : 'Create failed.');
      this.mode.set('error');
    }
  }

  #buildPayload(f: FormState): VendorCreateRequestDto {
    const numeric = (s: string): number | undefined => {
      const n = Number(s);
      return s.trim() && Number.isFinite(n) ? n : undefined;
    };
    const trimOrUndefined = (s: string): string | undefined =>
      s.trim().length > 0 ? s.trim() : undefined;

    return {
      name: f.name.trim(),
      website: trimOrUndefined(f.website),
      vendor_tier: trimOrUndefined(f.vendorTier),
      category: trimOrUndefined(f.category),
      payment_terms: trimOrUndefined(f.paymentTerms),
      annual_revenue: numeric(f.annualRevenue),
      sla_response_hours: numeric(f.slaResponseHours),
      sla_resolution_days: numeric(f.slaResolutionDays),
      vendor_status: trimOrUndefined(f.vendorStatus),
      onboarded_date: trimOrUndefined(f.onboardedDate),
      billing_city: trimOrUndefined(f.billingCity),
      billing_state: trimOrUndefined(f.billingState),
      billing_country: trimOrUndefined(f.billingCountry),
    };
  }

  #reset(): void {
    this.form.set(EMPTY);
    this.mode.set('idle');
    this.errorMsg.set('');
  }
}
