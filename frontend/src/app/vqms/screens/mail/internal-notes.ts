import { ChangeDetectionStrategy, Component, OnChanges, SimpleChanges, computed, input, signal } from '@angular/core';
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
export class InternalNotes implements OnChanges {
  readonly notes = input.required<readonly MailInternalNote[]>();
  readonly messageId = input.required<string>();

  protected readonly list = signal<readonly MailInternalNote[]>([]);
  protected readonly draft = signal<string>('');
  protected readonly canPost = computed<boolean>(() => this.draft().trim().length > 0);

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['notes'] || changes['messageId']) {
      this.list.set(this.notes());
      this.draft.set('');
    }
  }

  protected post(): void {
    const text = this.draft().trim();
    if (!text) return;
    const ts = new Date().toISOString().replace('T', ' ').slice(0, 16);
    this.list.update((l) => [...l, { author: 'Anika Verma', ts, text }]);
    this.draft.set('');
  }

  protected textValue(e: Event): string {
    return (e.target as HTMLTextAreaElement).value;
  }
}
