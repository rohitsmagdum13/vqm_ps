import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

@Component({
  selector: 'vq-drawer',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (open()) {
      <div
        class="fixed inset-0 z-40"
        style="background: rgba(0,0,0,.32);"
        (click)="closed.emit()"
      >
        <div
          class="absolute right-0 top-0 bottom-0 panel fade-up overflow-auto"
          [style.width.px]="width()"
          style="border-left: 1px solid var(--line-strong);"
          (click)="$event.stopPropagation()"
        >
          <ng-content />
        </div>
      </div>
    }
  `,
})
export class Drawer {
  readonly open = input.required<boolean>();
  readonly width = input<number>(720);
  readonly closed = output<void>();
}
