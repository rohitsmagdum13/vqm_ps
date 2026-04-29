import { ChangeDetectionStrategy, Component } from '@angular/core';
import { Icon } from '../../ui/icon';
import { Mono } from '../../ui/mono';
import { HealthDot } from '../../ui/health-dot';
import { MAIL_SYNC } from '../../data/mail';

@Component({
  selector: 'vq-mail-sync-banner',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Icon, Mono, HealthDot],
  // No setIntervals here. The earlier version updated a `seconds` signal
  // every 1 s which caused continuous CD ticks on this component (in
  // zoneless mode that's still bounded, but it's a steady pulse of work
  // the page doesn't need). The "last synced" line shows the static
  // value from MAIL_SYNC instead.
  template: `
    <div
      class="flex items-center gap-3 px-6 py-2 border-b hairline"
      [style.background]="
        sync.graph_status !== 'healthy'
          ? 'color-mix(in oklch, var(--warn) 8%, var(--panel))'
          : 'var(--panel)'
      "
      style="font-size:11.5px;"
    >
      <span class="flex items-center gap-1.5">
        <vq-health-dot [status]="sync.graph_status" />
        <span class="ink-2" style="font-weight:500;">Microsoft Graph API</span>
        @if (sync.graph_status !== 'healthy') {
          <span style="color: var(--warn);">· {{ sync.graph_note }}</span>
        }
      </span>
      <span class="muted">|</span>
      <span class="muted">
        <vq-mono>vqms‑email‑intake‑queue</vq-mono> · {{ sync.sqs_visible }} visible /
        {{ sync.sqs_in_flight }} in‑flight / {{ sync.sqs_dlq }} DLQ
      </span>
      <span class="flex-1"></span>
      <span class="muted inline-flex items-center gap-1.5">
        <vq-icon name="refresh-cw" [size]="10" />
        last synced
        <vq-mono cssClass="ink-2" [size]="10.5">{{ sync.last_sync_seconds_ago }}s</vq-mono>
        ago
      </span>
    </div>
  `,
})
export class SyncBanner {
  protected readonly sync = MAIL_SYNC;
}
