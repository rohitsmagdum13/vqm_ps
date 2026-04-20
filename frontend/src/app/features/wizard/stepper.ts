import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

interface StepInfo {
  readonly n: number;
  readonly label: string;
}

const STEPS: readonly StepInfo[] = [
  { n: 1, label: 'Query Type' },
  { n: 2, label: 'Details' },
  { n: 3, label: 'Review' },
];

@Component({
  selector: 'app-wizard-stepper',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="flex items-center gap-2 flex-wrap">
      @for (s of steps; track s.n; let last = $last) {
        <div class="flex items-center gap-2">
          <div
            class="h-7 w-7 rounded-full flex items-center justify-center text-[11px] font-mono border"
            [class]="circleClass(s.n)"
          >
            @if (current() > s.n) {
              <span aria-hidden="true">✓</span>
            } @else {
              {{ s.n }}
            }
          </div>
          <div class="hidden sm:block">
            <div class="text-[9px] font-mono tracking-wider uppercase text-fg-dim">Step {{ s.n }}</div>
            <div class="text-[11px] font-medium" [class]="labelClass(s.n)">{{ s.label }}</div>
          </div>
          @if (!last) {
            <div class="h-px w-8 sm:w-12" [class]="lineClass(s.n)"></div>
          }
        </div>
      }
    </div>
  `,
})
export class WizardStepper {
  readonly current = input.required<number>();
  protected readonly steps = STEPS;

  protected readonly statusFor = computed(() => (n: number) => {
    const c = this.current();
    return c > n ? 'done' : c === n ? 'curr' : 'todo';
  });

  protected circleClass(n: number): string {
    const c = this.current();
    if (c > n) return 'bg-success text-surface border-success';
    if (c === n) return 'bg-primary text-surface border-primary';
    return 'bg-surface-2 text-fg-dim border-border-light';
  }

  protected labelClass(n: number): string {
    return this.current() < n ? 'text-fg-dim' : 'text-fg';
  }

  protected lineClass(n: number): string {
    const c = this.current();
    if (c > n) return 'bg-success';
    if (c === n) return 'bg-primary';
    return 'bg-border-light';
  }
}
