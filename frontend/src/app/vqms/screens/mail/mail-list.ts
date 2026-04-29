import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { Icon } from '../../ui/icon';
import { Mono } from '../../ui/mono';
import { Empty } from '../../ui/empty';
import { MailRow } from './mail-row';
import { MAIL_FOLDERS } from '../../data/mail';
import type { MailFolderId, MailThread } from '../../data/mail';

export type MailSort = 'newest' | 'oldest' | 'priority' | 'confidence';

@Component({
  selector: 'vq-mail-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Icon, Mono, Empty, MailRow],
  host: { style: 'display: contents;' },
  template: `
    <div
      class="flex flex-col flex-shrink-0"
      style="width:360px; border-right: 1px solid var(--line); background: var(--panel);"
    >
      <div class="px-3 py-2.5 border-b hairline">
        <div class="flex items-center gap-2">
          <input
            type="checkbox"
            [checked]="allChecked()"
            (change)="toggleAll()"
            style="accent-color: var(--accent);"
          />
          <div class="relative flex-1">
            <span style="position:absolute; left:8px; top:50%; transform:translateY(-50%);">
              <vq-icon name="search" [size]="12" cssClass="muted" />
            </span>
            <input
              class="w-full"
              style="padding-left:28px; font-size:12.5px;"
              placeholder="Search mail…"
              [value]="search()"
              (input)="searchChange.emit(input($event))"
            />
            <vq-mono
              cssClass="muted"
              [size]="10"
              style="position:absolute; right:8px; top:50%; transform:translateY(-50%);"
              >/</vq-mono
            >
          </div>
          <select
            [value]="sort()"
            (change)="sortChange.emit(input($event))"
            style="font-size:11.5px; padding:5px 6px;"
          >
            <option value="newest">Newest</option>
            <option value="oldest">Oldest</option>
            <option value="priority">Priority</option>
            <option value="confidence">Confidence</option>
          </select>
        </div>

        @if (bulk().size > 0) {
          <div class="flex items-center gap-1.5 mt-2 fade-up">
            <vq-mono cssClass="text-accent" [size]="11" [weight]="600"
              >{{ bulk().size }} selected</vq-mono
            >
            <div class="flex-1"></div>
            <button class="btn" style="padding:3px 8px; font-size:11px;">
              <vq-icon name="mail-open" [size]="11" /> Mark read
            </button>
            <button class="btn" style="padding:3px 8px; font-size:11px;">
              <vq-icon name="archive" [size]="11" /> Archive
            </button>
            <button class="btn" style="padding:3px 8px; font-size:11px;">
              <vq-icon name="link" [size]="11" /> Link query
            </button>
            <button
              class="btn"
              style="padding:3px 8px; font-size:11px;"
              (click)="clearBulk.emit()"
            >
              <vq-icon name="x" [size]="11" />
            </button>
          </div>
        }

        <div class="flex items-center justify-between mt-2">
          <div class="muted" style="font-size:11px;">
            <vq-mono>{{ rows().length }}</vq-mono>
            message{{ rows().length === 1 ? '' : 's' }} · {{ folderLabel() }}
          </div>
          <div
            class="flex items-center gap-2 muted"
            style="font-size:10.5px;"
          >
            <vq-mono>J</vq-mono><span>/</span><vq-mono>K</vq-mono>
            <span>navigate</span>
          </div>
        </div>
      </div>

      <div class="flex-1 overflow-y-auto">
        @if (rows().length === 0) {
          <vq-empty
            title="No messages"
            desc="Nothing matches the current folder + filters."
            icon="mail"
          />
        }
        @for (r of rows(); track r.message_id) {
          <vq-mail-row
            [row]="r"
            [selected]="selectedId() === r.message_id"
            [checked]="bulk().has(r.message_id)"
            (select)="selectRow.emit(r.message_id)"
            (toggleCheck)="toggleOne.emit(r.message_id)"
          />
        }
      </div>
    </div>
  `,
})
export class MailList {
  readonly rows = input.required<readonly MailThread[]>();
  readonly selectedId = input<string | null>(null);
  readonly bulk = input.required<ReadonlySet<string>>();
  readonly search = input<string>('');
  readonly sort = input<MailSort>('newest');
  readonly folder = input.required<MailFolderId>();

  readonly selectRow = output<string>();
  readonly toggleOne = output<string>();
  readonly toggleAllRequested = output<void>();
  readonly clearBulk = output<void>();
  readonly searchChange = output<string>();
  readonly sortChange = output<string>();

  protected readonly allChecked = computed<boolean>(() => {
    const sel = this.bulk();
    const rows = this.rows();
    return sel.size > 0 && sel.size === rows.length;
  });

  protected readonly folderLabel = computed<string>(() => {
    const f = MAIL_FOLDERS.find((x) => x.id === this.folder());
    return f?.label ?? '';
  });

  protected toggleAll(): void {
    this.toggleAllRequested.emit();
  }

  protected input(e: Event): string {
    const t = e.target as HTMLInputElement | HTMLSelectElement;
    return t.value;
  }
}
