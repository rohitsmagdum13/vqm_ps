import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { toSignal } from '@angular/core/rxjs-interop';
import { ToastService } from '../../core/notifications/toast.service';
import { VendorsStore } from '../../data/vendors.store';
import { EmptyStateComponent } from '../../shared/ui/empty-state/empty-state';
import { SpinnerComponent } from '../../shared/ui/spinner/spinner';
import type { Vendor, VendorStatus, VendorTier } from '../../shared/models/vendor';
import { VendorFormModal } from './vendor-form-modal';

function tierBadgeClass(tier: VendorTier | null): string {
  switch (tier) {
    case 'PLATINUM':
      return 'bg-slate-500/15 text-slate-700 border border-slate-500/40';
    case 'GOLD':
      return 'bg-yellow-500/15 text-yellow-700 border border-yellow-500/40';
    case 'SILVER':
      return 'bg-zinc-400/20 text-zinc-700 border border-zinc-500/40';
    case 'BRONZE':
      return 'bg-amber-700/15 text-amber-800 border border-amber-700/40';
    default:
      return 'bg-surface-2 text-fg-dim border border-border-light';
  }
}

function statusBadgeClass(status: VendorStatus | null): string {
  if (status === 'ACTIVE') return 'bg-success/15 text-success border border-success/30';
  if (status === 'INACTIVE') return 'bg-fg-dim/15 text-fg-dim border border-border-light';
  return 'bg-surface-2 text-fg-dim border border-border-light';
}

function locationLabel(v: Vendor): string {
  const parts = [v.billing_city, v.billing_state].filter((x): x is string => !!x && x.length > 0);
  return parts.length > 0 ? parts.join(', ') : '—';
}

function slaLabel(v: Vendor): string {
  const h = v.sla_response_hours;
  const d = v.sla_resolution_days;
  if (h === null && d === null) return '—';
  const hLabel = h === null ? '—' : `${h}h`;
  const dLabel = d === null ? '—' : `${d}d`;
  return `${hLabel} / ${dLabel}`;
}

@Component({
  selector: 'app-admin-vendors-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, EmptyStateComponent, SpinnerComponent, VendorFormModal],
  template: `
    <section class="space-y-6 animate-[fade-up_0.3s_ease-out]">
      <header
        class="flex items-start justify-between gap-3 flex-wrap rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm p-4 sm:p-5"
      >
        <div class="flex items-start gap-3 min-w-0 flex-1">
          <div
            class="h-10 w-10 shrink-0 rounded-full bg-primary/10 text-primary flex items-center justify-center text-lg"
          >🏭</div>
          <div class="min-w-0">
            <h1 class="text-lg sm:text-xl font-semibold text-fg tracking-tight">Vendor Accounts</h1>
            <p class="mt-1 text-xs text-fg-dim">
              Manage vendor records synced from Salesforce. Create, edit, or remove vendors below.
            </p>
          </div>
        </div>
        <button
          type="button"
          (click)="openCreate()"
          class="shrink-0 inline-flex items-center gap-2 rounded-[var(--radius-sm)] bg-primary text-surface text-xs font-semibold px-3 sm:px-4 py-2 hover:bg-primary/90 transition"
          aria-label="Create new vendor"
        >
          <span aria-hidden="true">＋</span>
          <span>New Vendor</span>
        </button>
      </header>

      <div class="flex items-center gap-3 flex-wrap">
        <label
          class="flex items-center gap-2 rounded-[var(--radius-sm)] bg-surface border border-border-light px-3 py-2 flex-1 min-w-[240px] max-w-md"
        >
          <span class="text-fg-dim text-sm" aria-hidden="true">🔍</span>
          <input
            type="search"
            [formControl]="searchCtrl"
            placeholder="Search by name, vendor ID, city, website, category"
            class="flex-1 bg-transparent outline-none text-sm placeholder:text-fg-dim"
          />
        </label>
        <span class="text-[11px] font-mono uppercase tracking-wider text-fg-dim">
          {{ countLabel() }}
        </span>
        @if (loading()) {
          <ui-spinner size="sm" label="Loading vendors" />
        }
      </div>

      @if (error(); as err) {
        <div
          role="alert"
          class="rounded-[var(--radius-md)] border border-error/30 bg-error/10 text-error text-xs px-4 py-3"
        >
          Failed to load vendors: {{ err }}
          <button
            type="button"
            (click)="refresh()"
            class="ml-2 underline hover:no-underline"
          >Retry</button>
        </div>
      }

      @if (!hasLoaded() && loading()) {
        <div class="py-16 flex justify-center">
          <ui-spinner size="lg" label="Loading vendors" />
        </div>
      } @else if (rows().length === 0) {
        <ui-empty-state
          icon="🏭"
          title="No vendors"
          [message]="searchCtrl.value ? 'No vendors match your search.' : 'Create your first vendor to get started.'"
        >
          <button
            type="button"
            (click)="openCreate()"
            class="inline-flex items-center gap-2 rounded-[var(--radius-sm)] bg-primary text-surface text-xs font-semibold px-4 py-2 hover:bg-primary/90 transition"
          >＋ New Vendor</button>
        </ui-empty-state>
      } @else {
        <div
          class="rounded-[var(--radius-md)] bg-surface border border-border-light shadow-sm overflow-hidden"
        >
          <div class="overflow-x-auto">
            <table class="w-full border-collapse text-sm">
              <thead class="bg-surface-2 text-fg-dim">
                <tr>
                  <th class="px-3 sm:px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">Name</th>
                  <th class="hidden sm:table-cell px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">Tier</th>
                  <th class="hidden md:table-cell px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">Category</th>
                  <th class="hidden sm:table-cell px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">Status</th>
                  <th class="hidden lg:table-cell px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">Website</th>
                  <th class="hidden lg:table-cell px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">City</th>
                  <th class="hidden xl:table-cell px-4 py-2 text-left text-[10px] font-mono tracking-wider uppercase">SLA</th>
                  <th class="px-3 sm:px-4 py-2 text-right text-[10px] font-mono tracking-wider uppercase">Actions</th>
                </tr>
              </thead>
              <tbody>
                @for (v of rows(); track v.id) {
                  <tr class="border-t border-border-light hover:bg-surface-2 transition">
                    <td class="px-3 sm:px-4 py-3 text-fg font-medium max-w-[200px] sm:max-w-xs">
                      <div class="truncate" [title]="v.name">{{ v.name }}</div>
                      @if (v.vendor_id) {
                        <div class="text-[10px] font-mono text-fg-dim truncate">{{ v.vendor_id }}</div>
                      }
                      <div class="sm:hidden mt-1 text-[11px] text-fg-dim truncate">
                        {{ v.vendor_tier ?? '—' }}
                        @if (v.billing_city) {
                          <span> · {{ v.billing_city }}</span>
                        }
                      </div>
                    </td>
                    <td class="hidden sm:table-cell px-4 py-3 text-xs">
                      @if (v.vendor_tier) {
                        <span
                          class="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold"
                          [class]="tierBadgeClass(v.vendor_tier)"
                        >{{ v.vendor_tier }}</span>
                      } @else {
                        <span class="text-fg-dim">—</span>
                      }
                    </td>
                    <td class="hidden md:table-cell px-4 py-3 text-fg-dim text-xs whitespace-nowrap">{{ v.category ?? '—' }}</td>
                    <td class="hidden sm:table-cell px-4 py-3 text-xs">
                      @if (v.vendor_status) {
                        <span
                          class="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold"
                          [class]="statusBadgeClass(v.vendor_status)"
                        >{{ v.vendor_status }}</span>
                      } @else {
                        <span class="text-fg-dim">—</span>
                      }
                    </td>
                    <td class="hidden lg:table-cell px-4 py-3 text-xs">
                      @if (v.website) {
                        <a
                          [href]="v.website"
                          target="_blank"
                          rel="noopener"
                          class="text-primary hover:underline truncate inline-block max-w-[160px] align-bottom"
                          [title]="v.website"
                        >{{ v.website }}</a>
                      } @else {
                        <span class="text-fg-dim">—</span>
                      }
                    </td>
                    <td class="hidden lg:table-cell px-4 py-3 text-fg-dim text-xs whitespace-nowrap">{{ locationLabel(v) }}</td>
                    <td class="hidden xl:table-cell px-4 py-3 text-fg-dim text-xs whitespace-nowrap">{{ slaLabel(v) }}</td>
                    <td class="px-3 sm:px-4 py-3 text-right whitespace-nowrap">
                      <div class="inline-flex flex-col sm:flex-row items-end sm:items-center gap-1 sm:gap-0">
                        <button
                          type="button"
                          (click)="openEdit(v)"
                          class="text-xs text-primary hover:underline sm:mr-3"
                          [attr.aria-label]="'Edit ' + v.name"
                        >Edit</button>
                        @if (confirmingId() === v.id) {
                          <span class="inline-flex items-center gap-2">
                            <button
                              type="button"
                              (click)="confirmDelete(v)"
                              [disabled]="loading()"
                              class="text-xs text-error font-semibold hover:underline disabled:opacity-50"
                              [attr.aria-label]="'Confirm delete ' + v.name"
                            >Confirm?</button>
                            <button
                              type="button"
                              (click)="cancelDelete()"
                              class="text-xs text-fg-dim hover:text-fg"
                            >Cancel</button>
                          </span>
                        } @else {
                          <button
                            type="button"
                            (click)="askDelete(v.id)"
                            class="text-xs text-error hover:underline"
                            [attr.aria-label]="'Delete ' + v.name"
                          >Delete</button>
                        }
                      </div>
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        </div>
      }
    </section>

    <app-vendor-form-modal
      [(open)]="modalOpen"
      [vendor]="editing()"
      (saved)="onSaved()"
    />
  `,
})
export class AdminVendorsPage {
  readonly #store = inject(VendorsStore);
  readonly #toast = inject(ToastService);

  protected readonly rows = this.#store.filtered;
  protected readonly loading = this.#store.loading;
  protected readonly error = this.#store.error;
  protected readonly hasLoaded = this.#store.hasLoaded;

  protected readonly searchCtrl = new FormControl<string>('', { nonNullable: true });
  readonly #searchValue = toSignal(this.searchCtrl.valueChanges, { initialValue: '' });

  protected readonly modalOpen = signal<boolean>(false);
  protected readonly editing = signal<Vendor | null>(null);
  protected readonly confirmingId = signal<string | null>(null);

  protected readonly countLabel = computed<string>(() => {
    const n = this.rows().length;
    return `${n} vendor${n === 1 ? '' : 's'}`;
  });

  protected readonly tierBadgeClass = tierBadgeClass;
  protected readonly statusBadgeClass = statusBadgeClass;
  protected readonly locationLabel = locationLabel;
  protected readonly slaLabel = slaLabel;

  constructor() {
    effect(() => {
      this.#store.setSearch(this.#searchValue());
    });

    if (!this.#store.hasLoaded()) {
      this.#store.refresh();
    }
  }

  protected refresh(): void {
    this.#store.refresh();
  }

  protected openCreate(): void {
    this.editing.set(null);
    this.modalOpen.set(true);
  }

  protected openEdit(v: Vendor): void {
    this.editing.set(v);
    this.modalOpen.set(true);
  }

  protected onSaved(): void {
    this.editing.set(null);
  }

  protected askDelete(id: string): void {
    this.confirmingId.set(id);
  }

  protected cancelDelete(): void {
    this.confirmingId.set(null);
  }

  protected async confirmDelete(v: Vendor): Promise<void> {
    try {
      await this.#store.remove(v);
      this.#toast.show(`Vendor deleted · ${v.name}`, 'success');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Delete failed.';
      this.#toast.show(msg, 'error');
    } finally {
      this.confirmingId.set(null);
    }
  }
}
