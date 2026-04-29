import { ChangeDetectionStrategy, Component, input } from '@angular/core';

@Component({
  selector: 'vq-logo',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <svg [attr.width]="size()" [attr.height]="size()" viewBox="0 0 32 32" fill="none">
      <rect x="1" y="1" width="30" height="30" rx="3" fill="var(--ink)" />
      <path
        d="M9 10l5 12 4-9 5 9"
        stroke="var(--accent)"
        stroke-width="2.2"
        stroke-linecap="round"
        stroke-linejoin="round"
        fill="none"
      />
      <circle cx="23" cy="22" r="2" fill="var(--accent)" />
    </svg>
  `,
})
export class Logo {
  readonly size = input<number>(24);
}
