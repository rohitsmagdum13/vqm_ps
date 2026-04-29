import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { Icon } from './icon';
import { Mono } from './mono';

@Component({
  selector: 'vq-forbidden',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Icon, Mono],
  template: `
    <div class="flex items-center justify-center" style="min-height: 480px;">
      <div class="text-center fade-up" style="max-width: 380px;">
        <div
          style="width:56px; height:56px; border-radius:999px;
                 background: color-mix(in oklch, var(--bad) 12%, var(--panel));
                 display:inline-flex; align-items:center; justify-content:center;
                 margin-bottom:16px; color: var(--bad);"
        >
          <vq-icon name="lock" [size]="22" />
        </div>
        <div class="ink" style="font-size:18px; font-weight:600; letter-spacing:-.01em;">
          Access restricted
        </div>
        <div class="muted mt-1.5" style="font-size:13px;">
          Your role
          <vq-mono [color]="'var(--ink)'" [weight]="600">{{ role() }}</vq-mono>
          does not have permission to view
          <vq-mono>{{ view() }}</vq-mono>.
          Contact an administrator if you need access.
        </div>
        <button class="btn btn-accent mt-5" (click)="goHome.emit()">
          <vq-icon name="arrow-left" [size]="13" /> Back to allowed area
        </button>
      </div>
    </div>
  `,
})
export class Forbidden {
  readonly role = input.required<string>();
  readonly view = input.required<string>();
  readonly goHome = output<void>();
}
