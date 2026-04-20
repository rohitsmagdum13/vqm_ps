import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { Router } from '@angular/router';
import { AuthService } from '../../core/auth/auth.service';
import { QueriesStore } from '../../data/queries.store';
import { PortalHero } from './hero';
import { PortalKpiStrip } from './kpi-strip';
import { PortalQuickActions } from './quick-actions';
import { PortalRecentQueries } from './recent-queries';

@Component({
  selector: 'app-portal-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [PortalHero, PortalKpiStrip, PortalQuickActions, PortalRecentQueries],
  template: `
    <section class="space-y-8 animate-[fade-up_0.3s_ease-out]">
      <app-portal-hero
        [firstName]="firstName()"
        [company]="user().company"
        (newQuery)="goWizard()"
        (viewAll)="goQueries()"
      />

      <app-portal-kpi-strip
        [openCount]="openCount()"
        [resolvedCount]="resolvedCount()"
        (openQueries)="goQueries()"
      />

      <div>
        <div class="text-[10px] font-mono tracking-wider uppercase text-fg-dim mb-2">
          Quick Actions
        </div>
        <app-portal-quick-actions
          (newQuery)="goWizard()"
          (viewQueries)="goQueries()"
          (openPrefs)="goPrefs()"
        />
      </div>

      <div>
        <div class="flex items-center justify-between mb-2">
          <div class="text-[10px] font-mono tracking-wider uppercase text-fg-dim">
            Recent Queries
          </div>
          <button
            type="button"
            (click)="goQueries()"
            class="text-xs text-primary hover:underline"
          >View all →</button>
        </div>
        <app-portal-recent-queries
          [queries]="recent()"
          (open)="openQuery($event)"
        />
      </div>
    </section>
  `,
})
export class PortalPage {
  readonly #auth = inject(AuthService);
  readonly #store = inject(QueriesStore);
  readonly #router = inject(Router);

  protected readonly user = this.#auth.user;
  protected readonly firstName = computed(() => this.user().name.split(' ')[0]);

  protected readonly recent = this.#store.recent;
  protected readonly openCount = computed(() => {
    const s = this.#store.stats();
    return s.open + s.inProgress + s.awaiting;
  });
  protected readonly resolvedCount = computed(() => this.#store.stats().resolved);

  protected goWizard(): void { void this.#router.navigate(['/wizard']); }
  protected goQueries(): void { void this.#router.navigate(['/queries']); }
  protected goPrefs(): void { void this.#router.navigate(['/preferences']); }
  protected openQuery(id: string): void { void this.#router.navigate(['/queries', id]); }
}
