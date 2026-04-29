import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, signal } from '@angular/core';
import { Icon } from '../../ui/icon';
import { Mono } from '../../ui/mono';
import { HealthDot } from '../../ui/health-dot';
import { MAIL_SYNC } from '../../data/mail';

@Component({
  selector: 'vq-mail-sync-banner',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Icon, Mono, HealthDot],
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
      @if (newCount() > 0) {
        <button
          class="chip fade-up"
          style="background: var(--accent-soft); color: var(--accent); border-color: var(--accent); font-weight:600;"
          (click)="newCount.set(0)"
        >
          <vq-icon name="arrow-down" [size]="10" /> {{ newCount() }} new email{{
            newCount() === 1 ? '' : 's'
          }}
          — refresh
        </button>
      }
      <span class="muted inline-flex items-center gap-1.5">
        <vq-icon name="refresh-cw" [size]="10" />
        last synced
        <vq-mono cssClass="ink-2" [size]="10.5">{{ seconds() }}s</vq-mono>
        ago
      </span>
    </div>
  `,
})
export class SyncBanner implements OnInit, OnDestroy {
  protected readonly sync = MAIL_SYNC;
  protected readonly seconds = signal(MAIL_SYNC.last_sync_seconds_ago);
  protected readonly newCount = signal(0);

  #tick?: ReturnType<typeof setInterval>;
  #pulse?: ReturnType<typeof setInterval>;

  ngOnInit(): void {
    this.#tick = setInterval(() => this.seconds.update((s) => (s + 1) % 90), 1000);
    this.#pulse = setInterval(() => {
      if (Math.random() > 0.55) this.newCount.update((c) => c + 1);
    }, 9000);
  }

  ngOnDestroy(): void {
    if (this.#tick) clearInterval(this.#tick);
    if (this.#pulse) clearInterval(this.#pulse);
  }
}
