import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { TopNav } from '../top-nav/top-nav';
import { PageHeader } from '../page-header/page-header';
import { ToastHost } from '../../notifications/toast';

@Component({
  selector: 'app-shell',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterOutlet, TopNav, PageHeader, ToastHost],
  template: `
    <div class="min-h-screen flex flex-col bg-bg">
      <app-top-nav />
      <main class="flex-1 w-full max-w-[1400px] mx-auto px-6 py-6">
        <app-page-header />
        <router-outlet />
      </main>
      <app-toast />
    </div>
  `,
})
export class Shell {}
