import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { Icon } from '../../ui/icon';
import { Mono } from '../../ui/mono';
import { Avatar } from '../../ui/avatar';
import { Tier } from '../../ui/tier';
import type { Vendor } from '../../data/models';

@Component({
  selector: 'vq-mail-vendor-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Icon, Mono, Avatar, Tier],
  template: `
    @if (vendor()) {
      <div class="px-4 py-4 border-b hairline">
        <div
          class="muted uppercase tracking-wider mb-2"
          style="font-size:9.5px; font-weight:600;"
        >
          Vendor
        </div>
        <div class="flex items-start gap-3">
          <vq-avatar [name]="vendor()!.name" [size]="36" />
          <div class="flex-1 min-w-0">
            <div class="ink" style="font-size:13px; font-weight:600;">{{ vendor()!.name }}</div>
            <vq-mono cssClass="muted" [size]="10.5"
              >{{ vendor()!.vendor_id }} · {{ vendor()!.website }}</vq-mono
            >
            <div class="mt-1.5">
              <vq-tier [tier]="vendor()!.tier" />
            </div>
          </div>
        </div>

        <div class="grid grid-cols-2 gap-2 mt-3" style="font-size:11px;">
          <div>
            <div class="muted uppercase tracking-wider" style="font-size:9px; font-weight:600;">
              Open
            </div>
            <vq-mono [size]="13" [weight]="600" [color]="'var(--ink)'">{{ vendor()!.open_queries }}</vq-mono>
          </div>
          <div>
            <div class="muted uppercase tracking-wider" style="font-size:9px; font-weight:600;">P1</div>
            <vq-mono [size]="13" [weight]="600" [color]="p1Color()">{{ vendor()!.p1_open }}</vq-mono>
          </div>
          <div>
            <div class="muted uppercase tracking-wider" style="font-size:9px; font-weight:600;">
              Health
            </div>
            <vq-mono [size]="13" [weight]="600" [color]="healthColor()">{{ vendor()!.health }}</vq-mono>
          </div>
          <div>
            <div class="muted uppercase tracking-wider" style="font-size:9px; font-weight:600;">SLA</div>
            <vq-mono [size]="11.5" [color]="'var(--ink-2)'"
              >{{ vendor()!.sla_response_hours }}h/{{ vendor()!.sla_resolution_days }}d</vq-mono
            >
          </div>
        </div>

        <div class="muted mt-3" style="font-size:11px;">
          {{ vendor()!.category }} · {{ vendor()!.city }}, {{ vendor()!.country }}
        </div>
        <button
          class="btn w-full justify-center mt-3"
          style="font-size:11.5px;"
          (click)="open.emit()"
        >
          <vq-icon name="external-link" [size]="11" /> Open Vendor 360
        </button>
      </div>
    }
  `,
})
export class VendorMiniCard {
  readonly vendor = input<Vendor | null>(null);
  readonly open = output<void>();

  protected readonly p1Color = computed<string>(() => {
    const v = this.vendor();
    if (!v) return 'var(--ink)';
    return v.p1_open > 0 ? 'var(--bad)' : 'var(--ink)';
  });

  protected readonly healthColor = computed<string>(() => {
    const v = this.vendor();
    if (!v) return 'var(--ink)';
    return v.health > 85 ? 'var(--ok)' : v.health > 70 ? 'var(--warn)' : 'var(--bad)';
  });
}
