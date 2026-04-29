import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Icon } from '../ui/icon';
import { Logo } from '../ui/logo';
import { Mono } from '../ui/mono';
import type { Role } from '../services/role.service';
import { RoleService } from '../services/role.service';
import { SessionService } from '../services/session.service';

const ROLES: readonly Role[] = ['Admin', 'Reviewer', 'Vendor'];

type Mode = 'idle' | 'submitting';

@Component({
  selector: 'vq-login',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Icon, Logo, Mono],
  template: `
    <div class="min-h-screen flex">
      <div class="flex-1 flex items-center justify-center p-12">
        <div class="w-full max-w-md fade-up">
          <div class="flex items-center gap-2 mb-8">
            <vq-logo [size]="28" />
            <span class="ink" style="font-size:18px; font-weight:600; letter-spacing:-.01em;">VQMS</span>
            <vq-mono [size]="11" cssClass="ml-1 muted">v0.7.4‑rc1</vq-mono>
          </div>
          <div class="ink" style="font-size:26px; font-weight:600; letter-spacing:-.02em;">Sign in</div>
          <div class="muted mt-1.5 mb-6" style="font-size:13px;">
            Vendor Query Management System · Hexaware Technologies
          </div>

          <form class="flex flex-col gap-3" (submit)="submit($event)">
            <div>
              <div class="muted uppercase mb-1" style="font-size:10px; letter-spacing:.06em;">
                Username or email
              </div>
              <input
                class="w-full"
                autocomplete="username"
                [value]="username()"
                (input)="username.set(input($event))"
                [disabled]="mode() === 'submitting'"
              />
            </div>
            <div>
              <div class="muted uppercase mb-1" style="font-size:10px; letter-spacing:.06em;">
                Password
              </div>
              <input
                class="w-full"
                type="password"
                autocomplete="current-password"
                [value]="password()"
                (input)="password.set(input($event))"
                [disabled]="mode() === 'submitting'"
              />
            </div>
            <div>
              <div class="muted uppercase mb-1" style="font-size:10px; letter-spacing:.06em;">
                Sign in as
              </div>
              <div class="grid grid-cols-3 gap-2">
                @for (r of roles; track r) {
                  <label
                    class="flex items-center gap-2 p-2 rounded cursor-pointer"
                    [style.border]="role() === r ? '1px solid var(--accent)' : '1px solid var(--line)'"
                    [style.background]="role() === r ? 'var(--accent-soft)' : 'transparent'"
                  >
                    <input
                      type="radio"
                      name="vqms-login-role"
                      [checked]="role() === r"
                      (change)="role.set(r)"
                      [disabled]="mode() === 'submitting'"
                      style="accent-color: var(--accent);"
                    />
                    <span style="font-size:12.5px;">{{ r }}</span>
                  </label>
                }
              </div>
            </div>

            @if (errorMsg()) {
              <div
                class="flex items-start gap-2 p-3 rounded"
                style="background: color-mix(in oklch, var(--bad) 8%, var(--panel)); border: 1px solid var(--bad); color: var(--bad); font-size: 12.5px;"
              >
                <vq-icon name="alert-circle" [size]="14" />
                <span>{{ errorMsg() }}</span>
              </div>
            }

            <button
              type="submit"
              class="btn btn-accent w-full justify-center mt-2"
              [disabled]="!canSubmit()"
            >
              @if (mode() === 'submitting') {
                <vq-icon name="rotate-cw" [size]="14" />
                Signing in…
              } @else {
                <vq-icon name="log-in" [size]="14" />
                Sign in
              }
            </button>
            <button type="button" class="btn w-full justify-center" disabled>
              <vq-icon name="key" [size]="13" /> Continue with SSO (Microsoft)
            </button>
          </form>

          <div class="muted mt-6" style="font-size:11.5px;">
            By signing in you agree to the internal acceptable‑use policy. JWT issued via
            <vq-mono>POST /auth/login</vq-mono> with 8h TTL.
          </div>
        </div>
      </div>
      <div
        class="hidden lg:flex flex-1 items-center justify-center"
        style="background: var(--ink); color: var(--bg); padding: 64px;"
      >
        <div class="max-w-md">
          <div class="mono" style="font-size:11px; opacity:.6; letter-spacing:.1em;">
            VENDOR QUERY MANAGEMENT
          </div>
          <div style="font-size:32px; font-weight:600; letter-spacing:-.02em; margin-top:12px; line-height:1.15;">
            Three paths.<br />One inbox.<br />
            <span style="color: var(--accent);">Zero dropped queries.</span>
          </div>
          <div class="mt-6" style="font-size:13.5px; opacity:.8; line-height:1.6;">
            AI‑resolved, human‑routed, or sent to triage — every vendor email lands in the right
            place, with full audit, SLA tracking, and episodic memory write‑back.
          </div>
          <div class="grid grid-cols-3 gap-4 mt-10">
            <div>
              <div class="mono" style="font-size:22px; font-weight:600; color: var(--bg);">91.4%</div>
              <div class="mono" style="font-size:10.5px; opacity:.55; letter-spacing:.06em; text-transform:uppercase; margin-top:4px;">Resolution rate</div>
            </div>
            <div>
              <div class="mono" style="font-size:22px; font-weight:600; color: var(--bg);">4h 12m</div>
              <div class="mono" style="font-size:10.5px; opacity:.55; letter-spacing:.06em; text-transform:uppercase; margin-top:4px;">Avg response</div>
            </div>
            <div>
              <div class="mono" style="font-size:22px; font-weight:600; color: var(--bg);">&lt; 1%</div>
              <div class="mono" style="font-size:10.5px; opacity:.55; letter-spacing:.06em; text-transform:uppercase; margin-top:4px;">DLQ rate</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
})
export class LoginPage {
  readonly #session = inject(SessionService);
  readonly #role = inject(RoleService);
  readonly #router = inject(Router);

  protected readonly roles = ROLES;
  protected readonly role = signal<Role>('Admin');
  protected readonly username = signal<string>('');
  protected readonly password = signal<string>('');
  protected readonly mode = signal<Mode>('idle');
  protected readonly errorMsg = signal<string>('');

  protected readonly canSubmit = computed<boolean>(
    () =>
      this.mode() !== 'submitting' &&
      this.username().trim().length > 0 &&
      this.password().length > 0,
  );

  protected input(e: Event): string {
    return (e.target as HTMLInputElement).value;
  }

  protected async submit(e: Event): Promise<void> {
    e.preventDefault();
    if (!this.canSubmit()) return;

    this.mode.set('submitting');
    this.errorMsg.set('');

    try {
      const session = await this.#session.loginWithCredentials(
        this.username().trim(),
        this.password(),
        this.role(),
      );
      this.#role.setRole(session.role);
      const target = session.role === 'Vendor' ? '/portal' : '/app/overview';
      await this.#router.navigateByUrl(target);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Sign in failed.';
      this.errorMsg.set(msg);
      this.mode.set('idle');
    }
  }
}
