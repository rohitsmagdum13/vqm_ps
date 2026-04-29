import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { Icon } from '../ui/icon';
import { Mono } from '../ui/mono';
import { ConfidenceBar } from '../ui/confidence-bar';
import { SectionHead } from '../ui/section-head';
import { EndpointsButton } from '../ui/endpoints-button';
import { EndpointsDrawer } from '../ui/endpoints-drawer';
import { KB_ARTICLES } from '../data/mock-data';
import { ENDPOINTS_KB } from '../data/endpoints';
import { RoleService } from '../services/role.service';

interface ArticleRow {
  readonly id: string;
  readonly title: string;
  readonly last_updated: string;
  readonly uses_30d: number;
  readonly hit_rate: number;
  readonly bars: readonly { h: number; bg: string }[];
}

@Component({
  selector: 'vq-kb-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Icon, Mono, ConfidenceBar, SectionHead, EndpointsButton, EndpointsDrawer],
  template: `
    <div class="p-6 max-w-[1600px] mx-auto fade-up">
      <div class="flex items-center justify-between mb-5">
        <div>
          <div class="ink" style="font-size:20px; font-weight:600; letter-spacing:-.02em;">
            Knowledge base &amp; embeddings
          </div>
          <div class="muted mt-1" style="font-size:12.5px;">
            memory.embedding_index · pgvector 0.7.0 · Titan Embed v2 (1536‑dim)
          </div>
        </div>
        <div class="flex items-center gap-2">
          <button class="btn"><vq-icon name="upload" [size]="13" /> Index article</button>
          <button class="btn btn-primary"><vq-icon name="plus" [size]="13" /> Re‑embed all</button>
          <vq-endpoints-button (clicked)="endpointsOpen.set(true)" />
        </div>
      </div>

      <vq-endpoints-drawer
        [open]="endpointsOpen()"
        title="Knowledge base · backend contract"
        subtitle="src/api/routes/kb.py · pgvector + Bedrock embed"
        [endpoints]="endpoints"
        [role]="role.role()"
        (closed)="endpointsOpen.set(false)"
      />

      <div class="grid grid-cols-12 gap-3 mb-3">
        <div class="panel p-4 col-span-4" style="border-radius:4px;">
          <div class="muted uppercase mb-2" style="font-size:10px; letter-spacing:.04em;">Index size</div>
          <div class="ink" style="font-size:26px; font-weight:600;">{{ articles.length }}</div>
          <div class="muted" style="font-size:11px;">articles · 1,536 dimensions each</div>
        </div>
        <div class="panel p-4 col-span-4" style="border-radius:4px;">
          <div class="muted uppercase mb-2" style="font-size:10px; letter-spacing:.04em;">Avg cosine on hit</div>
          <div class="ink" style="font-size:26px; font-weight:600;">0.84</div>
          <div class="muted" style="font-size:11px;">retrieval threshold ≥ 0.80</div>
        </div>
        <div class="panel p-4 col-span-4" style="border-radius:4px;">
          <div class="muted uppercase mb-2" style="font-size:10px; letter-spacing:.04em;">KB‑hit rate (Path A)</div>
          <div class="ink" style="font-size:26px; font-weight:600; color: var(--ok);">91.2%</div>
          <div class="muted" style="font-size:11px;">last 30 days</div>
        </div>
      </div>

      <div class="panel p-4 mb-3" style="border-radius:4px;">
        <vq-section-head title="Probe similarity" desc="Test what the retriever returns for a hypothetical query" />
        <div class="flex items-center gap-2">
          <input class="flex-1" placeholder='e.g. "vendor wants to update bank account"' />
          <button class="btn btn-accent"><vq-icon name="zap" [size]="13" /> Embed &amp; search</button>
        </div>
      </div>

      <div class="panel" style="border-radius:4px; overflow:hidden;">
        <div class="p-3 border-b hairline flex items-center justify-between">
          <input
            placeholder="Filter articles…"
            [value]="filter()"
            (input)="filter.set(input($event))"
            style="width:280px;"
          />
          <vq-mono cssClass="muted">{{ filtered().length }} articles</vq-mono>
        </div>
        <table class="vqms-table">
          <thead>
            <tr>
              <th>Article</th>
              <th>Last updated</th>
              <th>Uses (30d)</th>
              <th>Hit rate</th>
              <th>Embedding</th>
            </tr>
          </thead>
          <tbody>
            @for (a of filtered(); track a.id) {
              <tr>
                <td>
                  <div class="ink-2" style="font-size:12.5px; font-weight:500;">{{ a.title }}</div>
                  <vq-mono cssClass="muted" [size]="10.5">{{ a.id }}</vq-mono>
                </td>
                <td><vq-mono cssClass="muted" [size]="11.5">{{ a.last_updated }}</vq-mono></td>
                <td><vq-mono>{{ a.uses_30d }}</vq-mono></td>
                <td><vq-confidence-bar [value]="a.hit_rate" [threshold]="0.80" /></td>
                <td>
                  <div class="flex items-center gap-0.5">
                    @for (b of a.bars; track $index) {
                      <span
                        [style.width.px]="3"
                        [style.height.px]="b.h"
                        [style.background]="b.bg"
                        [style.border-radius.px]="1"
                        style="display: inline-block;"
                      ></span>
                    }
                  </div>
                </td>
              </tr>
            }
          </tbody>
        </table>
      </div>
    </div>
  `,
})
export class KbPage {
  protected readonly role = inject(RoleService);
  protected readonly endpointsOpen = signal(false);
  protected readonly endpoints = ENDPOINTS_KB;

  protected readonly articles = KB_ARTICLES;
  protected readonly filter = signal<string>('');

  protected readonly filtered = computed<readonly ArticleRow[]>(() => {
    const term = this.filter().toLowerCase();
    const filtered = this.articles.filter(
      (a) => !term || a.title.toLowerCase().includes(term) || a.id.includes(term),
    );
    return filtered.map((a) => ({
      ...a,
      bars: this.#bars(a.id, a.hit_rate),
    }));
  });

  protected input(e: Event): string {
    return (e.target as HTMLInputElement).value;
  }

  #bars(id: string, hit: number): readonly { h: number; bg: string }[] {
    const code = id.charCodeAt(3);
    return Array.from({ length: 24 }, (_, i) => ({
      h: 12 + Math.sin(i * hit * 7) * 4,
      bg: `oklch(${65 + ((i * 7) % 25)}% .12 ${(i * 21 + code) % 360})`,
    }));
  }
}
