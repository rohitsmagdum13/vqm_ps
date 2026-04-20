import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, output, signal } from '@angular/core';

const STAGES: readonly string[] = [
  'Connecting to VQMS pipeline…',
  'Validating your submission…',
  'Scoring priority & category…',
  'Routing to the resolution queue…',
  'Generating query ID…',
];

const STAGE_MS = 450;

@Component({
  selector: 'app-wizard-submitting',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="flex flex-col items-center justify-center py-12 gap-4 text-center">
      <div
        class="h-12 w-12 rounded-full border-4 border-primary/20 border-t-primary animate-spin"
        aria-hidden="true"
      ></div>
      <div class="text-sm font-medium text-fg">Submitting your query</div>
      <div class="text-xs font-mono text-fg-dim min-h-4">{{ stage() }}</div>
      <ul class="mt-2 space-y-1 text-[11px] font-mono text-fg-dim">
        @for (s of stages; track $index; let i = $index) {
          <li class="flex items-center gap-2">
            <span
              class="inline-block h-1.5 w-1.5 rounded-full"
              [class]="i <= index() ? 'bg-success' : 'bg-border-light'"
            ></span>
            <span [class]="i <= index() ? 'text-fg' : ''">{{ s }}</span>
          </li>
        }
      </ul>
    </div>
  `,
})
export class WizardSubmitting implements OnInit, OnDestroy {
  readonly done = output<void>();

  protected readonly stages = STAGES;
  protected readonly index = signal(0);
  protected readonly stage = signal(STAGES[0]);

  #timer: ReturnType<typeof setInterval> | null = null;

  ngOnInit(): void {
    this.#timer = setInterval(() => {
      const next = this.index() + 1;
      if (next >= STAGES.length) {
        this.#clear();
        this.done.emit();
        return;
      }
      this.index.set(next);
      this.stage.set(STAGES[next]);
    }, STAGE_MS);
  }

  ngOnDestroy(): void {
    this.#clear();
  }

  #clear(): void {
    if (this.#timer !== null) {
      clearInterval(this.#timer);
      this.#timer = null;
    }
  }
}
