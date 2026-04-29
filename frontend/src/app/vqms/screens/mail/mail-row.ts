import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { Icon } from '../../ui/icon';
import { Mono } from '../../ui/mono';
import { PathBadge } from '../../ui/path-badge';
import { fmtMailTime } from '../../data/mail';
import type { MailThread } from '../../data/mail';

@Component({
  selector: 'vq-mail-row',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Icon, Mono, PathBadge],
  template: `
    <div
      (click)="select.emit()"
      class="px-3 py-2.5 cursor-pointer fade-up"
      [style.border-bottom]="'1px solid var(--line)'"
      [style.background]="selected() ? 'var(--accent-soft)' : 'transparent'"
      [style.border-left]="selected() ? '2px solid var(--accent)' : '2px solid transparent'"
    >
      <div class="flex items-start gap-2">
        <input
          type="checkbox"
          [checked]="checked()"
          (change)="$event.stopPropagation()"
          (click)="onCheck($event)"
          style="accent-color: var(--accent); margin-top:4px;"
        />
        <div style="width:6px; margin-top:7px; flex-shrink:0;">
          @if (unread()) {
            <span
              style="display:block; width:6px; height:6px; border-radius:999px; background: var(--accent);"
            ></span>
          }
        </div>
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2">
            <span
              class="ink truncate"
              [style.font-size.px]="13"
              [style.font-weight]="unread() ? 600 : 500"
              style="flex:1; min-width:0;"
            >
              @if (outbound()) {
                <vq-icon name="corner-up-right" [size]="11" cssClass="muted" />
                {{ row().from_name || 'You' }}
              } @else {
                {{ row().from_name }}
              }
            </span>
            <vq-mono cssClass="muted" [size]="10.5">{{ when() }}</vq-mono>
          </div>

          <div class="flex items-center gap-1.5 mt-0.5">
            <vq-mono cssClass="muted" [size]="10">{{ row().vendor_id }}</vq-mono>
            <span class="muted" style="font-size:10px;">·</span>
            <span class="muted truncate" style="font-size:11px;">{{ row().vendor_name }}</span>
            @if (row()._flagged) {
              <vq-icon name="flag" [size]="10" cssClass="text-accent" />
            }
          </div>

          <div
            class="ink-2 truncate mt-1"
            [style.font-size.px]="12.5"
            [style.font-weight]="unread() ? 500 : 400"
          >
            {{ row().subject }}
          </div>

          <div class="muted truncate mt-0.5" style="font-size:11.5px;">{{ snippet() }}…</div>

          <div class="flex items-center gap-1.5 mt-1.5 flex-wrap">
            <vq-path-badge [letter]="row().processing_path" size="sm" />
            <span
              class="chip"
              style="padding:1px 5px; font-size:10px;"
              [style.color]="confColor()"
              [style.border-color]="'var(--line)'"
            >
              <span
                [style.width.px]="4"
                [style.height.px]="4"
                [style.border-radius]="'999px'"
                [style.background]="confColor()"
                style="display:inline-block; margin-right:4px;"
              ></span>
              <vq-mono [size]="10">{{ row().confidence_score.toFixed(2) }}</vq-mono>
            </span>
            @if (row()._has_ai_draft && row()._direction === 'inbound') {
              <span
                class="chip"
                style="padding:1px 5px; font-size:10px; color: var(--accent); border-color: var(--accent); background: var(--accent-soft);"
              >
                <vq-icon name="sparkles" [size]="9" /> AI draft
              </span>
            }
            @if (row().attachments.length > 0) {
              <span class="muted inline-flex items-center" style="font-size:10.5px;">
                <vq-icon name="paperclip" [size]="10" />
                <vq-mono [size]="10" cssClass="ml-0.5">{{ row().attachments.length }}</vq-mono>
              </span>
            }
            @if (row()._sla_pct !== null) {
              <span class="muted inline-flex items-center gap-1" style="font-size:10.5px;">
                <span
                  style="width:24px; height:3px; background: var(--line); border-radius:2px; overflow:hidden; display:inline-block;"
                >
                  <span
                    style="display:block; height:100%;"
                    [style.width.%]="row()._sla_pct"
                    [style.background]="slaColor()"
                  ></span>
                </span>
                <vq-mono [size]="10" [color]="slaColor()">{{ row()._sla_pct }}%</vq-mono>
              </span>
            }
            <span class="flex-1"></span>
            <vq-mono cssClass="muted" [size]="10">{{ row().query_id }}</vq-mono>
          </div>
        </div>
      </div>
    </div>
  `,
})
export class MailRow {
  readonly row = input.required<MailThread>();
  readonly selected = input<boolean>(false);
  readonly checked = input<boolean>(false);

  readonly select = output<void>();
  readonly toggleCheck = output<MouseEvent>();

  protected readonly unread = computed<boolean>(() => this.row()._status === 'unread');
  protected readonly outbound = computed<boolean>(() => this.row()._direction === 'outbound');
  protected readonly when = computed<string>(() => fmtMailTime(this.row().received_at));

  protected readonly confColor = computed<string>(() => {
    const c = this.row().confidence_score;
    return c >= 0.85 ? 'var(--ok)' : c >= 0.6 ? 'var(--warn)' : 'var(--bad)';
  });

  protected readonly slaColor = computed<string>(() => {
    const p = this.row()._sla_pct;
    if (p === null) return 'var(--muted)';
    return p >= 95 ? 'var(--bad)' : p >= 70 ? 'var(--warn)' : 'var(--ok)';
  });

  protected readonly snippet = computed<string>(() => {
    const text = (this.row().body_text || '').split('\n').join(' ');
    return text.slice(0, 88);
  });

  protected onCheck(e: MouseEvent): void {
    e.stopPropagation();
    this.toggleCheck.emit(e);
  }
}
