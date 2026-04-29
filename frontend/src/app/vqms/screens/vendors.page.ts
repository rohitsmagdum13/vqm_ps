import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Icon } from '../ui/icon';
import { Mono } from '../ui/mono';
import { Avatar } from '../ui/avatar';
import { Tier } from '../ui/tier';
import { Donut } from '../ui/donut';
import { Empty } from '../ui/empty';
import { EndpointsButton } from '../ui/endpoints-button';
import { EndpointsDrawer } from '../ui/endpoints-drawer';
import { ENDPOINTS_VENDORS } from '../data/endpoints';
import { RoleService } from '../services/role.service';
import { VendorsStore } from '../services/vendors.store';
import { VendorFormDrawer } from './vendor-form.drawer';

@Component({
  selector: 'vq-vendors-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Icon, Mono, Avatar, Tier, Donut, Empty, VendorFormDrawer, EndpointsButton, EndpointsDrawer],
  template: `
    <div class="p-6 max-w-[1600px] mx-auto fade-up">
      <div class="flex items-center justify-between mb-5">
        <div>
          <div class="ink" style="font-size:20px; font-weight:600; letter-spacing:-.02em;">Vendors</div>
          <div class="muted mt-1 flex items-center gap-2" style="font-size:12.5px;">
            <span>{{ all().length }} active · sourced from Salesforce <vq-mono>Vendor_Account__c</vq-mono></span>
            @if (status() === 'live') {
              <span class="chip" style="color: var(--ok); border-color: var(--ok);">
                <vq-icon name="check-circle" [size]="10" /> Live
              </span>
            }
            @if (status() === 'loading') {
              <span class="chip">
                <vq-icon name="rotate-cw" [size]="10" /> Loading…
              </span>
            }
            @if (status() === 'error') {
              <span class="chip" style="color: var(--bad); border-color: var(--bad);" [title]="error() ?? ''">
                <vq-icon name="alert-circle" [size]="10" /> {{ error() }}
              </span>
            }
            @if (status() === 'idle') {
              <span class="chip" style="color: var(--muted);">
                <vq-icon name="info" [size]="10" /> Mock data
              </span>
            }
          </div>
        </div>
        <div class="flex items-center gap-2">
          <input
            placeholder="Search vendors…"
            [value]="search()"
            (input)="search.set(input($event))"
            style="width:240px;"
          />
          <button class="btn" (click)="refresh()" [disabled]="status() === 'loading'">
            <vq-icon name="rotate-cw" [size]="13" /> Refresh
          </button>
          <button class="btn"><vq-icon name="download" [size]="13" /> Export</button>
          @if (canCreate()) {
            <button class="btn btn-primary" (click)="openForm()">
              <vq-icon name="plus" [size]="13" /> New vendor
            </button>
          }
          <vq-endpoints-button (clicked)="endpointsOpen.set(true)" />
        </div>
      </div>

      <vq-endpoints-drawer
        [open]="endpointsOpen()"
        title="Vendors · backend contract"
        subtitle="src/api/routes/vendors.py · synced from Salesforce every 5 min"
        [endpoints]="endpoints"
        [role]="role.role()"
        (closed)="endpointsOpen.set(false)"
      />

      <vq-vendor-form-drawer
        [open]="formOpen()"
        (closed)="closeForm()"
        (created)="onCreated($event)"
      />

      <div class="panel" style="border-radius:4px; overflow:hidden;">
        @if (status() === 'loading' && all().length === 0) {
          <div class="p-12 text-center muted" style="font-size:13px;">
            <vq-icon name="rotate-cw" [size]="20" cssClass="muted mb-2" />
            <div>Loading vendors from Salesforce…</div>
          </div>
        } @else {
          <table class="vqms-table">
            <thead>
              <tr>
                <th>Vendor</th><th>Tier</th><th>Category</th><th>Region</th>
                <th>Open queries</th><th>Health</th><th>SLA</th>
                <th style="text-align:right">Annual rev.</th>
              </tr>
            </thead>
            <tbody>
              @if (filtered().length === 0) {
                <tr>
                  <td colspan="8">
                    <vq-empty
                      icon="building-2"
                      title="No vendors match"
                      [desc]="search() ? 'Try clearing the search filter.' : 'Salesforce returned no active vendors.'"
                    />
                  </td>
                </tr>
              }
              @for (v of filtered(); track v.vendor_id) {
                <tr (click)="open(v.vendor_id)">
                  <td>
                    <div class="flex items-center gap-3">
                      <vq-avatar [name]="v.name" [size]="28" />
                      <div>
                        <div class="ink" style="font-size:13px; font-weight:500;">{{ v.name }}</div>
                        <vq-mono cssClass="muted" [size]="10.5">
                          {{ v.vendor_id }} · {{ v.website }}
                        </vq-mono>
                      </div>
                    </div>
                  </td>
                  <td><vq-tier [tier]="v.tier" /></td>
                  <td class="ink-2" style="font-size:12.5px;">{{ v.category }}</td>
                  <td class="muted" style="font-size:12px;">{{ v.city }}, {{ v.country }}</td>
                  <td>
                    <span style="font-size:12.5px;">
                      <vq-mono [weight]="600">{{ v.open_queries }}</vq-mono>
                      @if (v.p1_open > 0) {
                        <span style="color: var(--bad); margin-left:6px;">·
                          <vq-mono>{{ v.p1_open }}P1</vq-mono>
                        </span>
                      }
                    </span>
                  </td>
                  <td>
                    <div class="flex items-center gap-2">
                      <vq-donut [pct]="v.health" />
                      <vq-mono
                        [weight]="600"
                        [color]="
                          v.health > 85 ? 'var(--ok)' : v.health > 70 ? 'var(--warn)' : 'var(--bad)'
                        "
                        >{{ v.health }}</vq-mono
                      >
                    </div>
                  </td>
                  <td>
                    <vq-mono cssClass="muted">
                      {{ v.sla_response_hours }}h / {{ v.sla_resolution_days }}d
                    </vq-mono>
                  </td>
                  <td style="text-align:right;">
                    <vq-mono>\${{ revenue(v.annual_revenue) }}</vq-mono>
                  </td>
                </tr>
              }
            </tbody>
          </table>
        }
      </div>
    </div>
  `,
})
export class VendorsPage {
  readonly #router = inject(Router);
  readonly #store = inject(VendorsStore);
  readonly #role = inject(RoleService);

  protected readonly all = this.#store.vendors;
  protected readonly status = this.#store.status;
  protected readonly error = this.#store.error;
  protected readonly search = signal<string>('');
  protected readonly formOpen = signal<boolean>(false);
  protected readonly canCreate = computed<boolean>(() => this.#role.role() === 'Admin');
  protected readonly role = this.#role;
  protected readonly endpointsOpen = signal(false);
  protected readonly endpoints = ENDPOINTS_VENDORS;

  protected readonly filtered = computed(() => {
    const term = this.search().toLowerCase();
    return this.all().filter(
      (v) => !term || v.name.toLowerCase().includes(term) || v.vendor_id.includes(term),
    );
  });

  protected input(e: Event): string {
    return (e.target as HTMLInputElement).value;
  }

  protected open(vendorId: string): void {
    this.#router.navigate(['/app/vendors', vendorId]);
  }

  protected revenue(n: number): string {
    return (n / 1_000_000).toFixed(1) + 'M';
  }

  protected refresh(): void {
    void this.#store.refresh();
  }

  protected openForm(): void {
    this.formOpen.set(true);
  }

  protected closeForm(): void {
    this.formOpen.set(false);
  }

  protected onCreated(vendorId: string): void {
    this.formOpen.set(false);
    if (vendorId) {
      void this.#router.navigate(['/app/vendors', vendorId]);
    }
  }
}
