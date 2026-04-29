import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export type PathLetter = 'A' | 'B' | 'C';

const COLORS: Record<PathLetter, string> = {
  A: 'var(--path-a)',
  B: 'var(--path-b)',
  C: 'var(--path-c)',
};

const LABELS: Record<PathLetter, string> = {
  A: 'AI‑resolved',
  B: 'Human team',
  C: 'Reviewer',
};

@Component({
  selector: 'vq-path-badge',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (!letter() || letter() === '—') {
      <span class="subtle mono text-xs">—</span>
    } @else {
      <span class="inline-flex items-center gap-1.5" [style.font-size.px]="small() ? 11 : 12">
        <span
          [style.width.px]="6"
          [style.height.px]="6"
          [style.border-radius]="'999px'"
          [style.background]="color()"
          style="display:inline-block;"
        ></span>
        <span class="mono" [style.font-weight]="600" [style.color]="color()">Path {{ letter() }}</span>
        @if (!small()) {
          <span class="muted">· {{ label() }}</span>
        }
      </span>
    }
  `,
})
export class PathBadge {
  readonly letter = input.required<string | null | undefined>();
  readonly size = input<'sm' | 'md'>('md');

  readonly small = computed<boolean>(() => this.size() === 'sm');
  readonly color = computed<string>(() => COLORS[this.letter() as PathLetter] ?? 'var(--muted)');
  readonly label = computed<string>(() => LABELS[this.letter() as PathLetter] ?? '');
}
