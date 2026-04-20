import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';
import { AuthService } from '../../core/auth/auth.service';
import { ToastService } from '../../core/notifications/toast.service';
import type { Role } from '../../shared/models/user';

@Component({
  selector: 'app-login-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  template: `
    <main
      class="min-h-screen grid place-items-center bg-bg font-sans px-4 py-8"
    >
      <section
        class="w-full max-w-md rounded-[var(--radius-lg)] bg-surface shadow-lg border border-border-light p-8"
      >
        <header class="text-center mb-6">
          <div
            class="mx-auto h-14 w-14 rounded-[var(--radius-md)] grid place-items-center bg-primary text-surface font-mono font-semibold text-lg tracking-wider"
          >
            VQ
          </div>
          <h1 class="mt-4 text-2xl font-semibold text-fg tracking-tight">
            Vendor Query Management
          </h1>
          <p class="mt-1 text-sm text-fg-dim">
            Sign in to continue
          </p>
        </header>

        <div
          class="grid grid-cols-2 gap-2 p-1 rounded-[var(--radius-sm)] bg-surface-2 border border-border-light mb-5"
          role="tablist"
        >
          <button
            type="button"
            role="tab"
            [attr.aria-selected]="role() === 'vendor'"
            (click)="setRole('vendor')"
            class="py-2 rounded-[6px] text-sm font-medium transition"
            [class]="tabClass('vendor')"
          >
            🏭 Vendor
          </button>
          <button
            type="button"
            role="tab"
            [attr.aria-selected]="role() === 'admin'"
            (click)="setRole('admin')"
            class="py-2 rounded-[6px] text-sm font-medium transition"
            [class]="tabClass('admin')"
          >
            🛡 Admin
          </button>
        </div>

        <form [formGroup]="form" (ngSubmit)="submit()" class="space-y-4">
          <label class="block">
            <span class="block text-xs font-medium text-fg-dim uppercase tracking-wider mb-1">
              Email or Username
            </span>
            <input
              type="text"
              formControlName="email"
              autocomplete="username"
              class="w-full rounded-[var(--radius-sm)] border border-border-light bg-surface px-3 py-2 text-sm text-fg focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
          </label>

          <label class="block">
            <span class="block text-xs font-medium text-fg-dim uppercase tracking-wider mb-1">
              Password
            </span>
            <input
              type="password"
              formControlName="password"
              autocomplete="current-password"
              class="w-full rounded-[var(--radius-sm)] border border-border-light bg-surface px-3 py-2 text-sm text-fg focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
          </label>

          <button
            type="submit"
            [disabled]="loading() || form.invalid"
            class="w-full rounded-[var(--radius-sm)] bg-primary hover:bg-secondary text-surface font-medium py-2.5 transition disabled:opacity-60 disabled:cursor-not-allowed"
          >
            @if (loading()) {
              <span>{{ loadingMsg() }}</span>
            } @else {
              <span>Sign in as {{ role() === 'admin' ? 'Admin' : 'Vendor' }}</span>
            }
          </button>
        </form>

        <p class="mt-6 text-center text-xs text-fg-dim">
          Sign in with your tbl_users credentials
        </p>
      </section>
    </main>
  `,
})
export class LoginPage {
  readonly #auth = inject(AuthService);
  readonly #router = inject(Router);
  readonly #toast = inject(ToastService);

  protected readonly role = signal<Role>('vendor');
  protected readonly loading = signal<boolean>(false);
  protected readonly loadingStep = signal<number>(0);

  #tickHandle: number | null = null;

  private readonly loadingMsgs = ['Authenticating…', 'Verifying permissions…', 'Loading workspace…'] as const;

  protected readonly loadingMsg = computed(
    () => this.loadingMsgs[Math.min(this.loadingStep(), this.loadingMsgs.length - 1)],
  );

  protected readonly form = new FormGroup({
    email: new FormControl<string>('', {
      nonNullable: true,
      validators: [Validators.required, Validators.minLength(3)],
    }),
    password: new FormControl<string>('', {
      nonNullable: true,
      validators: [Validators.required, Validators.minLength(4)],
    }),
  });

  protected setRole(r: Role): void {
    this.role.set(r);
  }

  protected tabClass(r: Role): string {
    return this.role() === r
      ? 'bg-surface text-primary shadow-sm border border-border-light'
      : 'text-fg-dim hover:text-fg';
  }

  protected submit(): void {
    if (this.form.invalid || this.loading()) return;

    const { email, password } = this.form.getRawValue();
    const role = this.role();

    this.loading.set(true);
    this.loadingStep.set(0);
    this.#startTicker();

    this.#auth.loginWithCredentials(email, password, role).subscribe({
      next: () => {
        this.#stopTicker();
        this.loading.set(false);
        void this.#router.navigate([role === 'admin' ? '/admin' : '/portal']);
      },
      error: (err: unknown) => {
        this.#stopTicker();
        this.loading.set(false);
        this.#toast.show(this.#errorMessage(err), 'error', 4500);
      },
    });
  }

  #errorMessage(err: unknown): string {
    if (err instanceof HttpErrorResponse) {
      const detail =
        err.error && typeof err.error === 'object' && 'detail' in err.error
          ? (err.error as { detail?: unknown }).detail
          : null;
      if (typeof detail === 'string' && detail.length > 0) return detail;
      if (err.status === 0) return 'Cannot reach the server. Is the backend running?';
      if (err.status === 401) return 'Invalid credentials';
      return `Login failed (${err.status})`;
    }
    if (err instanceof Error) return err.message;
    return 'Login failed';
  }

  #startTicker(): void {
    this.#tickHandle = window.setInterval(() => {
      this.loadingStep.update((s) => s + 1);
    }, 700);
  }

  #stopTicker(): void {
    if (this.#tickHandle !== null) {
      window.clearInterval(this.#tickHandle);
      this.#tickHandle = null;
    }
  }
}
