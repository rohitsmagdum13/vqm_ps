import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

interface StatusStyle {
  readonly bg: string;
  readonly fg: string;
  readonly label: string;
}

const STYLES: Record<string, StatusStyle> = {
  RESOLVED: {
    bg: 'color-mix(in oklch, var(--ok) 14%, var(--panel))',
    fg: 'var(--ok)',
    label: 'Resolved',
  },
  DELIVERING: {
    bg: 'color-mix(in oklch, var(--info) 14%, var(--panel))',
    fg: 'var(--info)',
    label: 'Delivering',
  },
  DRAFTING: {
    bg: 'color-mix(in oklch, var(--info) 14%, var(--panel))',
    fg: 'var(--info)',
    label: 'Drafting',
  },
  VALIDATING: {
    bg: 'color-mix(in oklch, var(--info) 14%, var(--panel))',
    fg: 'var(--info)',
    label: 'Validating',
  },
  ROUTING: {
    bg: 'color-mix(in oklch, var(--info) 14%, var(--panel))',
    fg: 'var(--info)',
    label: 'Routing',
  },
  ANALYZING: {
    bg: 'color-mix(in oklch, var(--info) 14%, var(--panel))',
    fg: 'var(--info)',
    label: 'Analyzing',
  },
  AWAITING_RESOLUTION: {
    bg: 'color-mix(in oklch, var(--warn) 14%, var(--panel))',
    fg: 'var(--warn)',
    label: 'Awaiting',
  },
  PAUSED: {
    bg: 'color-mix(in oklch, var(--warn) 14%, var(--panel))',
    fg: 'var(--warn)',
    label: 'Paused',
  },
  REOPENED: {
    bg: 'color-mix(in oklch, var(--warn) 14%, var(--panel))',
    fg: 'var(--warn)',
    label: 'Reopened',
  },
  CLOSED: { bg: 'var(--bg)', fg: 'var(--muted)', label: 'Closed' },
  FAILED: {
    bg: 'color-mix(in oklch, var(--bad) 14%, var(--panel))',
    fg: 'var(--bad)',
    label: 'Failed',
  },
  MERGED_INTO_PARENT: { bg: 'var(--bg)', fg: 'var(--muted)', label: 'Merged' },
  RECEIVED: { bg: 'var(--bg)', fg: 'var(--ink-2)', label: 'Received' },
};

@Component({
  selector: 'vq-status',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span
      class="inline-flex items-center"
      [style.background]="style().bg"
      [style.color]="style().fg"
      style="font-size: 11px; padding: 2px 7px; border-radius: 3px; font-weight: 500; letter-spacing: .01em;"
    >
      <span
        [style.width.px]="4"
        [style.height.px]="4"
        [style.border-radius]="'999px'"
        [style.background]="style().fg"
        [style.margin-right.px]="5"
      ></span>
      {{ style().label }}
    </span>
  `,
})
export class Status {
  readonly value = input.required<string>();
  readonly style = computed<StatusStyle>(() => {
    const v = this.value();
    return STYLES[v] ?? { bg: 'var(--bg)', fg: 'var(--ink-2)', label: v };
  });
}
