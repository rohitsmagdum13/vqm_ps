import {
  ChangeDetectionStrategy,
  Component,
  HostListener,
  ElementRef,
  inject,
  signal,
} from '@angular/core';
import { Router } from '@angular/router';
import { AuthService } from '../../auth/auth.service';

@Component({
  selector: 'app-user-menu',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="relative">
      <button
        type="button"
        (click)="toggle()"
        [attr.aria-expanded]="open()"
        aria-haspopup="menu"
        class="flex items-center gap-3 rounded-[var(--radius-sm)] px-2 py-1 hover:bg-surface-2 transition"
      >
        <span class="text-right hidden md:block leading-tight">
          <span class="block text-xs font-medium text-fg">{{ user().name }}</span>
          <span class="block text-[10px] text-fg-dim uppercase tracking-wider">
            {{ user().role }} · {{ user().company }}
          </span>
        </span>
        <span
          class="h-9 w-9 rounded-full bg-primary text-surface grid place-items-center font-mono text-sm"
        >{{ user().ini }}</span>
      </button>

      @if (open()) {
        <div
          role="menu"
          class="absolute right-0 top-full mt-2 w-64 rounded-[var(--radius-md)] bg-surface border border-border-light shadow-lg overflow-hidden z-50 animate-[fade-up_0.15s_ease-out]"
        >
          <div class="p-4 border-b border-border-light bg-surface-2">
            <div class="flex items-center gap-3">
              <span
                class="h-10 w-10 rounded-full bg-primary text-surface grid place-items-center font-mono text-sm"
              >{{ user().ini }}</span>
              <div class="min-w-0">
                <div class="text-sm font-semibold text-fg truncate">{{ user().name }}</div>
                <div class="text-[11px] text-fg-dim truncate">{{ user().email }}</div>
              </div>
            </div>
            <div class="mt-3 flex items-center gap-1.5 text-[10px] font-mono text-fg-dim uppercase tracking-wider">
              <span
                class="inline-block h-1.5 w-1.5 rounded-full bg-success animate-pulse"
              ></span>
              {{ user().role }} · {{ user().company }}
            </div>
          </div>
          <button
            type="button"
            role="menuitem"
            (click)="goPrefs()"
            class="w-full text-left px-4 py-2.5 text-sm text-fg hover:bg-surface-2 transition flex items-center gap-2"
          >
            <span aria-hidden="true">⚙️</span>
            {{ role() === 'admin' ? 'Settings' : 'Preferences' }}
          </button>
          <button
            type="button"
            role="menuitem"
            (click)="logout()"
            class="w-full text-left px-4 py-2.5 text-sm text-error hover:bg-error/5 transition flex items-center gap-2 border-t border-border-light"
          >
            <span aria-hidden="true">↪</span>
            Sign out
          </button>
        </div>
      }
    </div>
  `,
})
export class UserMenu {
  readonly #auth = inject(AuthService);
  readonly #router = inject(Router);
  readonly #host = inject(ElementRef<HTMLElement>);

  protected readonly user = this.#auth.user;
  protected readonly role = this.#auth.role;
  protected readonly open = signal<boolean>(false);

  protected toggle(): void {
    this.open.update((v) => !v);
  }

  protected goPrefs(): void {
    this.open.set(false);
    void this.#router.navigate(['/preferences']);
  }

  protected async logout(): Promise<void> {
    this.open.set(false);
    await this.#auth.logout();
    void this.#router.navigate(['/login']);
  }

  @HostListener('document:click', ['$event'])
  protected onDocClick(ev: MouseEvent): void {
    if (!this.open()) return;
    const target = ev.target as Node | null;
    if (target && !this.#host.nativeElement.contains(target)) {
      this.open.set(false);
    }
  }

  @HostListener('document:keydown.escape')
  protected onEscape(): void {
    if (this.open()) this.open.set(false);
  }
}
