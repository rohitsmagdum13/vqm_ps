import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

@Component({
  selector: 'vq-avatar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span
      class="mono inline-flex items-center justify-center"
      [style.width.px]="size()"
      [style.height.px]="size()"
      [style.border-radius]="'999px'"
      [style.background]="bg()"
      [style.color]="'#000'"
      [style.font-size.px]="size() * 0.42"
      [style.font-weight]="600"
      >{{ initials() }}</span
    >
  `,
})
export class Avatar {
  readonly name = input.required<string>();
  readonly size = input<number>(24);

  readonly initials = computed<string>(() => {
    const name = this.name() || '?';
    return name
      .split(/\s+/)
      .filter(Boolean)
      .map((s) => s[0]!)
      .slice(0, 2)
      .join('');
  });

  readonly bg = computed<string>(() => {
    const name = this.name() || '?';
    let h = 0;
    for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) % 360;
    return `oklch(78% .07 ${h})`;
  });
}
