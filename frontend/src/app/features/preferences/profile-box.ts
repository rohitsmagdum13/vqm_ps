import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { AuthService } from '../../core/auth/auth.service';
import { ToastService } from '../../core/notifications/toast.service';

@Component({
  selector: 'app-profile-box',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @let u = user();
    <div
      class="flex items-center gap-4 rounded-[var(--radius-md)] border border-border-light bg-surface-2/60 p-4"
    >
      <div
        class="h-14 w-14 shrink-0 rounded-full bg-primary text-surface flex items-center justify-center text-base font-semibold"
        aria-hidden="true"
      >
        {{ u.ini }}
      </div>
      <div class="min-w-0 flex-1">
        <div class="text-sm font-semibold text-fg truncate">{{ u.name }}</div>
        <div class="mt-0.5 text-[11px] font-mono text-fg-dim truncate">{{ u.email }}</div>
        <div class="mt-1 flex items-center gap-2 text-[11px] text-fg-dim flex-wrap">
          <span aria-hidden="true">🏢</span>
          <span>{{ u.company }}</span>
          <span class="px-1.5 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20 text-[9px] font-mono uppercase tracking-wider">
            {{ u.role }}
          </span>
        </div>
      </div>
      <button
        type="button"
        (click)="onEdit()"
        class="shrink-0 inline-flex items-center rounded-[var(--radius-sm)] border border-border-light px-3 py-1.5 text-xs font-medium text-fg hover:bg-surface transition"
      >
        Edit
      </button>
    </div>
  `,
})
export class ProfileBox {
  readonly #auth = inject(AuthService);
  readonly #toast = inject(ToastService);
  protected readonly user = this.#auth.user;

  protected onEdit(): void {
    this.#toast.show('Profile editing coming soon', 'info');
  }
}
