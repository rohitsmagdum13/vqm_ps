import {
  ChangeDetectionStrategy,
  Component,
  effect,
  inject,
  input,
  model,
  output,
} from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { ToastService } from '../../core/notifications/toast.service';
import { VendorsStore } from '../../data/vendors.store';
import {
  VENDOR_STATUSES,
  VENDOR_TIERS,
  type Vendor,
  type VendorCreateInput,
  type VendorStatus,
  type VendorTier,
  type VendorUpdateInput,
} from '../../shared/models/vendor';

interface VendorForm {
  name: FormControl<string>;
  website: FormControl<string>;
  vendor_tier: FormControl<VendorTier | ''>;
  category: FormControl<string>;
  payment_terms: FormControl<string>;
  annual_revenue: FormControl<number | null>;
  sla_response_hours: FormControl<number | null>;
  sla_resolution_days: FormControl<number | null>;
  vendor_status: FormControl<VendorStatus | ''>;
  onboarded_date: FormControl<string>;
  billing_city: FormControl<string>;
  billing_state: FormControl<string>;
  billing_country: FormControl<string>;
}

const WEBSITE_PATTERN = /^(https?:\/\/)?([\w-]+\.)+[\w-]{2,}(\/\S*)?$/;

function nullableString(value: string): string | null {
  const t = value.trim();
  return t.length === 0 ? null : t;
}

function nullableNumber(value: number | null): number | null {
  if (value === null) return null;
  if (typeof value !== 'number' || Number.isNaN(value)) return null;
  return value;
}

@Component({
  selector: 'app-vendor-form-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  template: `
    @if (open()) {
      <div
        class="fixed inset-0 z-50 flex items-end md:items-center justify-center bg-fg/40 backdrop-blur-sm p-0 md:p-4 animate-[fade-up_0.2s_ease-out]"
        role="dialog"
        aria-modal="true"
        [attr.aria-label]="isEdit() ? 'Edit vendor' : 'New vendor'"
        (click)="onBackdrop($event)"
      >
        <div
          class="w-full md:max-w-2xl bg-surface rounded-t-[var(--radius-md)] md:rounded-[var(--radius-md)] shadow-xl border border-border-light flex flex-col max-h-[90vh]"
          (click)="$event.stopPropagation()"
        >
          <header class="flex items-center gap-2 px-4 py-3 border-b border-border-light">
            <span class="text-lg" aria-hidden="true">🏭</span>
            <h2 class="text-sm font-semibold text-fg flex-1">
              {{ isEdit() ? 'Edit vendor' : 'New vendor' }}
            </h2>
            <button
              type="button"
              (click)="close()"
              class="h-7 w-7 rounded-[var(--radius-sm)] text-fg-dim hover:bg-surface-2 transition"
              aria-label="Close"
            >✕</button>
          </header>

          <form [formGroup]="form" (ngSubmit)="save()" class="flex flex-col flex-1 min-h-0">
            <div class="flex-1 min-h-0 overflow-y-auto px-4 py-3 space-y-3">
              <label class="block">
                <span class="text-[11px] font-mono uppercase tracking-wider text-fg-dim">Name *</span>
                <input
                  type="text"
                  formControlName="name"
                  maxlength="255"
                  placeholder="Acme Corporation"
                  class="mt-1 w-full bg-transparent outline-none text-sm border-b border-border-light focus:border-primary py-1.5"
                />
                @if (showError('name')) {
                  <span class="mt-1 block text-[11px] text-error">Name is required.</span>
                }
              </label>

              <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <label class="block">
                  <span class="text-[11px] font-mono uppercase tracking-wider text-fg-dim">Tier</span>
                  <select
                    formControlName="vendor_tier"
                    class="mt-1 w-full bg-transparent outline-none text-sm border-b border-border-light focus:border-primary py-1.5"
                  >
                    <option value="">— None —</option>
                    @for (opt of tiers; track opt) {
                      <option [value]="opt">{{ opt }}</option>
                    }
                  </select>
                </label>

                <label class="block">
                  <span class="text-[11px] font-mono uppercase tracking-wider text-fg-dim">Status</span>
                  <select
                    formControlName="vendor_status"
                    class="mt-1 w-full bg-transparent outline-none text-sm border-b border-border-light focus:border-primary py-1.5"
                  >
                    <option value="">— None —</option>
                    @for (opt of statuses; track opt) {
                      <option [value]="opt">{{ opt }}</option>
                    }
                  </select>
                </label>
              </div>

              <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <label class="block">
                  <span class="text-[11px] font-mono uppercase tracking-wider text-fg-dim">Category</span>
                  <input
                    type="text"
                    formControlName="category"
                    maxlength="120"
                    placeholder="Managed Services"
                    class="mt-1 w-full bg-transparent outline-none text-sm border-b border-border-light focus:border-primary py-1.5"
                  />
                </label>

                <label class="block">
                  <span class="text-[11px] font-mono uppercase tracking-wider text-fg-dim">Payment Terms</span>
                  <input
                    type="text"
                    formControlName="payment_terms"
                    maxlength="60"
                    placeholder="Net-30"
                    class="mt-1 w-full bg-transparent outline-none text-sm border-b border-border-light focus:border-primary py-1.5"
                  />
                </label>
              </div>

              <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <label class="block">
                  <span class="text-[11px] font-mono uppercase tracking-wider text-fg-dim">Website</span>
                  <input
                    type="url"
                    formControlName="website"
                    placeholder="https://example.com"
                    class="mt-1 w-full bg-transparent outline-none text-sm border-b border-border-light focus:border-primary py-1.5"
                  />
                  @if (showError('website')) {
                    <span class="mt-1 block text-[11px] text-error">Enter a valid URL.</span>
                  }
                </label>

                <label class="block">
                  <span class="text-[11px] font-mono uppercase tracking-wider text-fg-dim">Annual Revenue (USD)</span>
                  <input
                    type="number"
                    min="0"
                    step="any"
                    formControlName="annual_revenue"
                    placeholder="1000000"
                    class="mt-1 w-full bg-transparent outline-none text-sm border-b border-border-light focus:border-primary py-1.5"
                  />
                  @if (showError('annual_revenue')) {
                    <span class="mt-1 block text-[11px] text-error">Must be zero or greater.</span>
                  }
                </label>
              </div>

              <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <label class="block">
                  <span class="text-[11px] font-mono uppercase tracking-wider text-fg-dim">SLA Response (hrs)</span>
                  <input
                    type="number"
                    min="0"
                    step="1"
                    formControlName="sla_response_hours"
                    placeholder="12"
                    class="mt-1 w-full bg-transparent outline-none text-sm border-b border-border-light focus:border-primary py-1.5"
                  />
                  @if (showError('sla_response_hours')) {
                    <span class="mt-1 block text-[11px] text-error">Must be zero or greater.</span>
                  }
                </label>

                <label class="block">
                  <span class="text-[11px] font-mono uppercase tracking-wider text-fg-dim">SLA Resolution (days)</span>
                  <input
                    type="number"
                    min="0"
                    step="1"
                    formControlName="sla_resolution_days"
                    placeholder="5"
                    class="mt-1 w-full bg-transparent outline-none text-sm border-b border-border-light focus:border-primary py-1.5"
                  />
                  @if (showError('sla_resolution_days')) {
                    <span class="mt-1 block text-[11px] text-error">Must be zero or greater.</span>
                  }
                </label>

                <label class="block">
                  <span class="text-[11px] font-mono uppercase tracking-wider text-fg-dim">Onboarded Date</span>
                  <input
                    type="date"
                    formControlName="onboarded_date"
                    class="mt-1 w-full bg-transparent outline-none text-sm border-b border-border-light focus:border-primary py-1.5"
                  />
                </label>
              </div>

              <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <label class="block">
                  <span class="text-[11px] font-mono uppercase tracking-wider text-fg-dim">Billing City</span>
                  <input
                    type="text"
                    formControlName="billing_city"
                    maxlength="40"
                    placeholder="Pune"
                    class="mt-1 w-full bg-transparent outline-none text-sm border-b border-border-light focus:border-primary py-1.5"
                  />
                </label>

                <label class="block">
                  <span class="text-[11px] font-mono uppercase tracking-wider text-fg-dim">Billing State</span>
                  <input
                    type="text"
                    formControlName="billing_state"
                    maxlength="40"
                    placeholder="Maharashtra"
                    class="mt-1 w-full bg-transparent outline-none text-sm border-b border-border-light focus:border-primary py-1.5"
                  />
                </label>

                <label class="block">
                  <span class="text-[11px] font-mono uppercase tracking-wider text-fg-dim">Billing Country</span>
                  <input
                    type="text"
                    formControlName="billing_country"
                    maxlength="40"
                    placeholder="India"
                    class="mt-1 w-full bg-transparent outline-none text-sm border-b border-border-light focus:border-primary py-1.5"
                  />
                </label>
              </div>
            </div>

            <footer class="flex items-center gap-2 px-4 py-3 border-t border-border-light bg-surface-2/50">
              <button
                type="submit"
                [disabled]="form.invalid || saving()"
                class="inline-flex items-center gap-2 rounded-[var(--radius-sm)] bg-primary text-surface text-xs font-semibold px-4 py-2 hover:bg-primary/90 transition disabled:opacity-50"
              >
                <span aria-hidden="true">💾</span>
                {{ isEdit() ? 'Save changes' : 'Create vendor' }}
              </button>
              <button
                type="button"
                (click)="close()"
                class="ml-auto text-xs font-medium text-fg-dim hover:text-fg transition px-2 py-1.5"
              >Cancel</button>
            </footer>
          </form>
        </div>
      </div>
    }
  `,
})
export class VendorFormModal {
  readonly open = model.required<boolean>();
  readonly vendor = input<Vendor | null>(null);
  readonly saved = output<void>();

  readonly #store = inject(VendorsStore);
  readonly #toast = inject(ToastService);

  protected readonly tiers = VENDOR_TIERS;
  protected readonly statuses = VENDOR_STATUSES;

  protected readonly form = new FormGroup<VendorForm>({
    name: new FormControl('', {
      nonNullable: true,
      validators: [Validators.required, Validators.maxLength(255)],
    }),
    website: new FormControl('', {
      nonNullable: true,
      validators: [Validators.pattern(WEBSITE_PATTERN)],
    }),
    vendor_tier: new FormControl<VendorTier | ''>('', { nonNullable: true }),
    category: new FormControl('', {
      nonNullable: true,
      validators: [Validators.maxLength(120)],
    }),
    payment_terms: new FormControl('', {
      nonNullable: true,
      validators: [Validators.maxLength(60)],
    }),
    annual_revenue: new FormControl<number | null>(null, {
      validators: [Validators.min(0)],
    }),
    sla_response_hours: new FormControl<number | null>(null, {
      validators: [Validators.min(0)],
    }),
    sla_resolution_days: new FormControl<number | null>(null, {
      validators: [Validators.min(0)],
    }),
    vendor_status: new FormControl<VendorStatus | ''>('', { nonNullable: true }),
    onboarded_date: new FormControl('', { nonNullable: true }),
    billing_city: new FormControl('', {
      nonNullable: true,
      validators: [Validators.maxLength(40)],
    }),
    billing_state: new FormControl('', {
      nonNullable: true,
      validators: [Validators.maxLength(40)],
    }),
    billing_country: new FormControl('', {
      nonNullable: true,
      validators: [Validators.maxLength(40)],
    }),
  });

  protected saving = this.#store.loading;

  constructor() {
    effect(() => {
      if (!this.open()) return;
      const v = this.vendor();
      this.form.reset({
        name: v?.name ?? '',
        website: v?.website ?? '',
        vendor_tier: v?.vendor_tier ?? '',
        category: v?.category ?? '',
        payment_terms: v?.payment_terms ?? '',
        annual_revenue: v?.annual_revenue ?? null,
        sla_response_hours: v?.sla_response_hours ?? null,
        sla_resolution_days: v?.sla_resolution_days ?? null,
        vendor_status: v?.vendor_status ?? '',
        onboarded_date: v?.onboarded_date ?? '',
        billing_city: v?.billing_city ?? '',
        billing_state: v?.billing_state ?? '',
        billing_country: v?.billing_country ?? '',
      });
    });
  }

  protected isEdit(): boolean {
    return this.vendor() !== null;
  }

  protected close(): void {
    this.open.set(false);
  }

  protected onBackdrop(_ev: MouseEvent): void {
    this.close();
  }

  protected showError(ctrl: keyof VendorForm): boolean {
    const c = this.form.controls[ctrl];
    return c.invalid && (c.dirty || c.touched);
  }

  protected async save(): Promise<void> {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      this.#toast.show('Fix the highlighted fields.', 'warn');
      return;
    }

    const v = this.form.getRawValue();
    const payload: VendorCreateInput = {
      name: v.name.trim(),
      website: nullableString(v.website),
      vendor_tier: v.vendor_tier === '' ? null : v.vendor_tier,
      category: nullableString(v.category),
      payment_terms: nullableString(v.payment_terms),
      annual_revenue: nullableNumber(v.annual_revenue),
      sla_response_hours: nullableNumber(v.sla_response_hours),
      sla_resolution_days: nullableNumber(v.sla_resolution_days),
      vendor_status: v.vendor_status === '' ? null : v.vendor_status,
      onboarded_date: nullableString(v.onboarded_date),
      billing_city: nullableString(v.billing_city),
      billing_state: nullableString(v.billing_state),
      billing_country: nullableString(v.billing_country),
    };

    try {
      const current = this.vendor();
      if (current) {
        const patch: VendorUpdateInput = payload;
        await this.#store.update(current, patch);
        this.#toast.show(`Vendor updated · ${payload.name}`, 'success');
      } else {
        await this.#store.create(payload);
        this.#toast.show(`Vendor created · ${payload.name}`, 'success');
      }
      this.saved.emit();
      this.close();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Save failed.';
      this.#toast.show(msg, 'error');
    }
  }
}
