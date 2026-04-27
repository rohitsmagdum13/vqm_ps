import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import type {
  DraftApprovalDetail,
  DraftApprovalListItem,
} from '../shared/models/draft-approval';
import { DraftApprovalsService } from './draft-approvals.service';

/**
 * Signal-based store backing the admin draft-approval queue.
 *
 * The list view subscribes to ``items()``; the detail view fetches a
 * specific case via ``loadDetail()`` and reads it back through
 * ``detail()``. Mutating actions (approve / reject) refresh the list so
 * the resolved/rejected case drops out of the queue.
 */
@Injectable({ providedIn: 'root' })
export class DraftApprovalsStore {
  readonly #api = inject(DraftApprovalsService);

  readonly #items = signal<readonly DraftApprovalListItem[]>([]);
  readonly #detail = signal<DraftApprovalDetail | null>(null);
  readonly #loading = signal<boolean>(false);
  readonly #loaded = signal<boolean>(false);
  readonly #error = signal<string | null>(null);

  readonly items = this.#items.asReadonly();
  readonly detail = this.#detail.asReadonly();
  readonly loading = this.#loading.asReadonly();
  readonly loaded = this.#loaded.asReadonly();
  readonly error = this.#error.asReadonly();

  readonly count = computed<number>(() => this.#items().length);

  async refresh(): Promise<void> {
    this.#loading.set(true);
    this.#error.set(null);
    try {
      const res = await firstValueFrom(this.#api.list());
      this.#items.set(res.drafts);
      this.#loaded.set(true);
    } catch (err: unknown) {
      this.#error.set(this.#errorMessage(err));
    } finally {
      this.#loading.set(false);
    }
  }

  async loadDetail(queryId: string): Promise<DraftApprovalDetail | null> {
    this.#loading.set(true);
    this.#error.set(null);
    try {
      const res = await firstValueFrom(this.#api.get(queryId));
      this.#detail.set(res);
      return res;
    } catch (err: unknown) {
      this.#error.set(this.#errorMessage(err));
      this.#detail.set(null);
      return null;
    } finally {
      this.#loading.set(false);
    }
  }

  /** Drop a row from the local list — used after approve/reject. */
  removeLocal(queryId: string): void {
    this.#items.set(this.#items().filter((d) => d.query_id !== queryId));
  }

  async approve(queryId: string): Promise<boolean> {
    try {
      await firstValueFrom(this.#api.approve(queryId));
      this.removeLocal(queryId);
      return true;
    } catch (err: unknown) {
      this.#error.set(this.#errorMessage(err));
      return false;
    }
  }

  async approveWithEdits(
    queryId: string,
    edits: { subject: string; body_html: string },
  ): Promise<boolean> {
    try {
      await firstValueFrom(this.#api.approveWithEdits(queryId, edits));
      this.removeLocal(queryId);
      return true;
    } catch (err: unknown) {
      this.#error.set(this.#errorMessage(err));
      return false;
    }
  }

  async reject(queryId: string, feedback: string): Promise<boolean> {
    try {
      await firstValueFrom(this.#api.reject(queryId, feedback));
      this.removeLocal(queryId);
      return true;
    } catch (err: unknown) {
      this.#error.set(this.#errorMessage(err));
      return false;
    }
  }

  #errorMessage(err: unknown): string {
    if (err instanceof Error) return err.message;
    if (
      typeof err === 'object' &&
      err !== null &&
      'message' in err &&
      typeof (err as { message: unknown }).message === 'string'
    ) {
      return (err as { message: string }).message;
    }
    return 'Unexpected error';
  }
}
