import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  input,
  signal,
} from '@angular/core';
import { Icon } from '../../ui/icon';
import { Mono } from '../../ui/mono';
import { Avatar } from '../../ui/avatar';
import type { MailInternalNote } from '../../data/mail';

@Component({
  selector: 'vq-mail-internal-notes',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Icon, Mono, Avatar],
  template: `
    <div class="px-4 py-4">
      <div class="flex items-center gap-2 mb-2">
        <vq-icon name="message-square" [size]="11" cssClass="muted" />
        <span
          class="muted uppercase tracking-wider"
          style="font-size:9.5px; font-weight:600;"
        >
          Internal notes
        </span>
        <span
          class="chip ml-auto"
          style="font-size:9.5px; padding:1px 5px; color: var(--warn); border-color: color-mix(in oklch, var(--warn) 30%, var(--line));"
        >
          <vq-icon name="eye-off" [size]="9" /> not visible to vendor
        </span>
      </div>

      <div class="space-y-2">
        @if (list().length === 0) {
          <div class="muted" style="font-size:11.5px;">No internal notes yet.</div>
        }
        @for (n of list(); track n.ts + n.author) {
          <div class="panel px-3 py-2" style="background: var(--bg); border-radius:4px;">
            <div class="flex items-center gap-2 mb-1">
              <vq-avatar [name]="n.author" [size]="16" />
              <span class="ink-2" style="font-size:11.5px; font-weight:500;">{{ n.author }}</span>
              <vq-mono cssClass="muted ml-auto" [size]="10">{{ n.ts }}</vq-mono>
            </div>
            <div class="ink-2" style="font-size:12px; line-height:1.5;">{{ n.text }}</div>
          </div>
        }
      </div>

      <div class="mt-2">
        <textarea
          [value]="draft()"
          (input)="draft.set(textValue($event))"
          placeholder="Add an internal note (only visible to VQMS team)…"
          style="width:100%; min-height:60px; font-size:12px; resize: vertical;"
        ></textarea>
        <button
          class="btn btn-primary mt-1.5 w-full justify-center"
          style="font-size:11.5px;"
          (click)="post()"
          [disabled]="!canPost()"
        >
          <vq-icon name="send" [size]="11" /> Post note
        </button>
      </div>
    </div>
  `,
})
export class InternalNotes {
  readonly notes = input.required<readonly MailInternalNote[]>();
  readonly messageId = input.required<string>();

  // Local notes posted in this session, keyed off messageId. Reset
  // automatically when the user switches to a different message via the
  // effect below — that's the only place we write a signal in response
  // to an input changing, and it runs OUTSIDE of change detection so it
  // doesn't compound with parent re-renders.
  protected readonly localAdditions = signal<readonly MailInternalNote[]>([]);
  protected readonly draft = signal<string>('');

  // Composed from upstream notes + this session's local additions. Pure
  // read of two signals — Angular memoises by reference equality, so
  // when the upstream `notes` reference is stable (see the EMPTY_NOTES
  // constant in mail-detail.ts) this computed doesn't re-evaluate.
  protected readonly list = computed<readonly MailInternalNote[]>(() => {
    const local = this.localAdditions();
    if (local.length === 0) return this.notes();
    return [...this.notes(), ...local];
  });

  protected readonly canPost = computed<boolean>(() => this.draft().trim().length > 0);

  constructor() {
    // Reset local state when the selected message changes. Reading
    // `messageId()` registers the dependency; the writes happen via the
    // effect runner (off the synchronous CD pass) so they don't trigger
    // an "expression changed after checked" cycle.
    effect(() => {
      this.messageId();
      this.localAdditions.set([]);
      this.draft.set('');
    });
  }

  protected post(): void {
    const text = this.draft().trim();
    if (!text) return;
    const ts = new Date().toISOString().replace('T', ' ').slice(0, 16);
    this.localAdditions.update((l) => [...l, { author: 'Anika Verma', ts, text }]);
    this.draft.set('');
  }

  protected textValue(e: Event): string {
    return (e.target as HTMLTextAreaElement).value;
  }
}
