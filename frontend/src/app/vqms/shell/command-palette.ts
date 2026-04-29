import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  HostListener,
  computed,
  inject,
  signal,
  viewChild,
  AfterViewInit,
} from '@angular/core';
import { Router } from '@angular/router';
import { Icon } from '../ui/icon';
import { Mono } from '../ui/mono';
import { NAV } from './nav';
import { DrawerService } from '../services/drawer.service';
import { QueriesStore } from '../services/queries.store';
import { RoleService } from '../services/role.service';
import { VendorsStore } from '../services/vendors.store';

interface PaletteItem {
  readonly kind: 'nav' | 'vendor' | 'query';
  readonly id: string;
  readonly label: string;
  readonly sub?: string;
  readonly icon: string;
}

@Component({
  selector: 'vq-command-palette',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Icon, Mono],
  template: `
    <div
      class="fixed inset-0 z-50 flex items-start justify-center pt-[12vh]"
      style="background: rgba(0,0,0,.4);"
      (click)="close()"
    >
      <div
        class="panel w-[600px] max-w-[92vw] fade-up"
        style="border-radius: 6px; overflow: hidden; box-shadow: 0 20px 50px rgba(0,0,0,.18);"
        (click)="$event.stopPropagation()"
      >
        <div class="flex items-center gap-2 px-4 py-3 border-b hairline">
          <vq-icon name="search" [size]="15" cssClass="muted" />
          <input
            #searchInput
            class="flex-1"
            style="background: transparent; font-size:14px; padding:0; border: none;"
            placeholder="Search queries, vendors, screens…"
            [value]="q()"
            (input)="q.set(input($event))"
          />
          <vq-mono [size]="10" cssClass="muted">esc</vq-mono>
        </div>
        <div class="max-h-[50vh] overflow-y-auto p-1">
          @for (it of items(); track it.kind + it.id) {
            <div class="nav-item" (click)="pick(it)">
              <vq-icon [name]="it.icon" [size]="13" cssClass="muted" />
              <div class="flex-1">
                <div class="ink-2" style="font-size:13px;">{{ it.label }}</div>
                @if (it.sub) {
                  <div class="muted" style="font-size:11.5px;">{{ it.sub }}</div>
                }
              </div>
              <vq-mono [size]="10" cssClass="muted">{{ it.kind }}</vq-mono>
            </div>
          }
          @if (items().length === 0) {
            <div class="muted text-center py-8" style="font-size:12px;">No results</div>
          }
        </div>
      </div>
    </div>
  `,
})
export class CommandPalette implements AfterViewInit {
  readonly #role = inject(RoleService);
  readonly #drawer = inject(DrawerService);
  readonly #router = inject(Router);
  readonly #vendors = inject(VendorsStore);
  readonly #queries = inject(QueriesStore);

  protected readonly q = signal<string>('');
  protected readonly searchInput = viewChild<ElementRef<HTMLInputElement>>('searchInput');

  ngAfterViewInit(): void {
    queueMicrotask(() => this.searchInput()?.nativeElement.focus());
  }

  protected items = computed<readonly PaletteItem[]>(() => {
    const allowed = this.#role.allowed();
    const out: PaletteItem[] = [];
    for (const n of NAV) {
      if (!allowed.includes(n.id)) continue;
      out.push({ kind: 'nav', id: n.id, label: n.label, icon: n.icon });
    }
    for (const v of this.#vendors.vendors()) {
      out.push({
        kind: 'vendor',
        id: v.vendor_id,
        label: v.name,
        sub: v.vendor_id,
        icon: 'building-2',
      });
    }
    for (const qr of this.#queries.list().slice(0, 30)) {
      out.push({
        kind: 'query',
        id: qr.query_id,
        label: qr.query_id,
        sub: qr.subject,
        icon: 'inbox',
      });
    }
    const term = this.q().toLowerCase();
    if (!term) return out.slice(0, 14);
    return out
      .filter(
        (i) =>
          i.label.toLowerCase().includes(term) || (i.sub && i.sub.toLowerCase().includes(term)),
      )
      .slice(0, 14);
  });

  protected input(e: Event): string {
    return (e.target as HTMLInputElement).value;
  }

  protected close(): void {
    this.#drawer.closePalette();
  }

  protected pick(it: PaletteItem): void {
    if (it.kind === 'nav') {
      const target = NAV.find((n) => n.id === it.id);
      if (target) this.#router.navigate([target.route]);
    } else if (it.kind === 'vendor') {
      this.#router.navigate(['/app/vendors', it.id]);
    } else if (it.kind === 'query') {
      const q = this.#queries.byId(it.id);
      if (q) this.#drawer.showQuery(q);
    }
    this.close();
  }

  @HostListener('window:keydown.escape')
  protected onEscape(): void {
    this.close();
  }
}
