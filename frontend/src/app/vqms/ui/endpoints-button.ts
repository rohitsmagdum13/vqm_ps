import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { Icon } from './icon';

@Component({
  selector: 'vq-endpoints-button',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Icon],
  template: `
    <button class="btn" type="button" (click)="clicked.emit()" title="Backend endpoints this UI calls">
      <vq-icon name="terminal" [size]="13" /> {{ label() }}
    </button>
  `,
})
export class EndpointsButton {
  readonly label = input<string>('Endpoints');
  readonly clicked = output<void>();
}
