import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { Icon } from '../../ui/icon';
import { Mono } from '../../ui/mono';
import { VENDORS } from '../../data/mock-data';
import { MAIL_FOLDERS } from '../../data/mail';
import type { MailFolderId } from '../../data/mail';

export interface MailFilters {
  vendor: string;
  path: 'ALL' | 'A' | 'B' | 'C';
  conf: 'ALL' | 'HIGH' | 'MED' | 'LOW';
  date: 'ALL' | '24H' | '7D' | '30D';
  sla: 'ALL' | 'OK' | 'RISK' | 'BAD';
  has_attach: boolean;
}

interface PathOpt {
  readonly id: MailFilters['path'];
  readonly label: string;
}
interface ConfOpt {
  readonly id: MailFilters['conf'];
  readonly label: string;
  readonly hint: string;
}
interface SlaOpt {
  readonly id: MailFilters['sla'];
  readonly label: string;
  readonly color: string;
}

const PATH_OPTS: readonly PathOpt[] = [
  { id: 'ALL', label: 'All' },
  { id: 'A', label: 'A' },
  { id: 'B', label: 'B' },
  { id: 'C', label: 'C' },
];

const CONF_OPTS: readonly ConfOpt[] = [
  { id: 'ALL', label: 'All', hint: '' },
  { id: 'HIGH', label: 'High', hint: '≥ 0.85' },
  { id: 'MED', label: 'Med', hint: '0.6–0.85' },
  { id: 'LOW', label: 'Low', hint: '< 0.6' },
];

const SLA_OPTS: readonly SlaOpt[] = [
  { id: 'ALL', label: 'All', color: 'var(--ink-2)' },
  { id: 'OK', label: 'On‑track', color: 'var(--ok)' },
  { id: 'RISK', label: 'At‑risk', color: 'var(--warn)' },
  { id: 'BAD', label: 'Breached', color: 'var(--bad)' },
];

@Component({
  selector: 'vq-mail-folder-rail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Icon, Mono],
  host: { style: 'display: contents;' },
  template: `
    <div
      class="flex flex-col flex-shrink-0"
      style="width:200px; border-right: 1px solid var(--line); background: var(--panel);"
    >
      <div class="px-3 pt-3 pb-2">
        <button
          class="btn btn-accent w-full justify-center"
          style="padding:7px 12px; font-size:12.5px;"
          (click)="composeRequested.emit()"
        >
          <vq-icon name="pen-line" [size]="13" /> Compose
          <vq-mono cssClass="ml-auto" [size]="10" [color]="'rgba(255,255,255,.7)'">C</vq-mono>
        </button>
      </div>

      <div class="px-2 pt-1 pb-2">
        @for (f of folders; track f.id) {
          <div
            class="nav-item"
            [class.active]="folder() === f.id"
            (click)="folderChange.emit(f.id)"
          >
            <vq-icon [name]="f.icon" [size]="13" />
            <span class="flex-1">{{ f.label }}</span>
            @if (counts()[f.id] > 0) {
              <vq-mono
                [size]="10.5"
                [color]="folder() === f.id ? 'white' : 'var(--muted)'"
                [cssClass]="folder() === f.id ? 'mail-pill mail-pill-active' : 'mail-pill'"
                >{{ counts()[f.id] }}</vq-mono
              >
            }
          </div>
        }
      </div>

      <style>
        .mail-pill {
          padding: 1px 6px;
          background: var(--line);
          border-radius: 999px;
        }
        .mail-pill-active {
          background: var(--accent);
        }
      </style>

      <div class="border-t hairline mx-2"></div>

      <div class="p-3 space-y-2.5 overflow-y-auto">
        <div
          class="muted uppercase tracking-wider"
          style="font-size:10px; font-weight:600;"
        >
          Filters
        </div>

        <div>
          <div class="muted uppercase tracking-wider mb-1" style="font-size:9.5px; font-weight:500;">
            Vendor
          </div>
          <select
            [value]="filters().vendor"
            (change)="patchVendor(input($event))"
            style="width:100%; font-size:12px;"
          >
            <option value="ALL">All vendors</option>
            @for (v of vendors; track v.vendor_id) {
              <option [value]="v.vendor_id">{{ v.vendor_id }} · {{ v.name }}</option>
            }
          </select>
        </div>

        <div>
          <div class="muted uppercase tracking-wider mb-1" style="font-size:9.5px; font-weight:500;">
            Path
          </div>
          <div class="flex gap-1">
            @for (p of pathOpts; track p.id) {
              <button
                type="button"
                class="btn"
                style="flex:1; padding:4px 6px; font-size:11px;"
                [style.background]="filters().path === p.id ? 'var(--accent-soft)' : 'var(--panel)'"
                [style.color]="filters().path === p.id ? 'var(--accent)' : 'var(--ink-2)'"
                [style.border-color]="filters().path === p.id ? 'var(--accent)' : 'var(--line-strong)'"
                (click)="patch('path', p.id)"
              >
                {{ p.label }}
              </button>
            }
          </div>
        </div>

        <div>
          <div class="muted uppercase tracking-wider mb-1" style="font-size:9.5px; font-weight:500;">
            Confidence
          </div>
          <div class="flex gap-1">
            @for (c of confOpts; track c.id) {
              <button
                type="button"
                class="btn"
                [title]="c.hint"
                style="flex:1; padding:4px 6px; font-size:11px;"
                [style.background]="filters().conf === c.id ? 'var(--accent-soft)' : 'var(--panel)'"
                [style.color]="filters().conf === c.id ? 'var(--accent)' : 'var(--ink-2)'"
                [style.border-color]="filters().conf === c.id ? 'var(--accent)' : 'var(--line-strong)'"
                (click)="patch('conf', c.id)"
              >
                {{ c.label }}
              </button>
            }
          </div>
        </div>

        <div>
          <div class="muted uppercase tracking-wider mb-1" style="font-size:9.5px; font-weight:500;">
            Date
          </div>
          <select
            [value]="filters().date"
            (change)="patchDate(input($event))"
            style="width:100%; font-size:12px;"
          >
            <option value="ALL">Any time</option>
            <option value="24H">Last 24 hours</option>
            <option value="7D">Last 7 days</option>
            <option value="30D">Last 30 days</option>
          </select>
        </div>

        <div>
          <div class="muted uppercase tracking-wider mb-1" style="font-size:9.5px; font-weight:500;">
            SLA status
          </div>
          <div class="flex gap-1">
            @for (s of slaOpts; track s.id) {
              <button
                type="button"
                class="btn"
                style="flex:1; padding:4px 4px; font-size:10.5px;"
                [style.background]="filters().sla === s.id ? 'var(--accent-soft)' : 'var(--panel)'"
                [style.color]="filters().sla === s.id ? 'var(--accent)' : s.color"
                [style.border-color]="filters().sla === s.id ? 'var(--accent)' : 'var(--line-strong)'"
                (click)="patch('sla', s.id)"
              >
                {{ s.label }}
              </button>
            }
          </div>
        </div>

        <label class="flex items-center gap-2 mt-1" style="font-size:12px; color: var(--ink-2);">
          <input
            type="checkbox"
            [checked]="filters().has_attach"
            (change)="patch('has_attach', checkbox($event))"
            style="accent-color: var(--accent);"
          />
          <vq-icon name="paperclip" [size]="11" cssClass="muted" />
          Has attachment
        </label>
      </div>
    </div>
  `,
})
export class FolderRail {
  readonly folder = input.required<MailFolderId>();
  readonly filters = input.required<MailFilters>();
  readonly counts = input.required<Readonly<Record<string, number>>>();

  readonly folderChange = output<MailFolderId>();
  readonly filtersChange = output<MailFilters>();
  readonly composeRequested = output<void>();

  protected readonly folders = MAIL_FOLDERS;
  protected readonly vendors = VENDORS;
  protected readonly pathOpts = PATH_OPTS;
  protected readonly confOpts = CONF_OPTS;
  protected readonly slaOpts = SLA_OPTS;

  protected patch<K extends keyof MailFilters>(key: K, value: MailFilters[K]): void {
    this.filtersChange.emit({ ...this.filters(), [key]: value });
  }

  protected patchVendor(value: string): void {
    this.patch('vendor', value);
  }

  protected patchDate(value: string): void {
    const allowed: readonly MailFilters['date'][] = ['ALL', '24H', '7D', '30D'];
    const next = (allowed as readonly string[]).includes(value)
      ? (value as MailFilters['date'])
      : 'ALL';
    this.patch('date', next);
  }

  protected input(e: Event): string {
    return (e.target as HTMLSelectElement).value;
  }

  protected checkbox(e: Event): boolean {
    return (e.target as HTMLInputElement).checked;
  }
}
