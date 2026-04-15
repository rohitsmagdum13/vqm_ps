import { Injectable } from '@angular/core';

/** In-memory store for the multi-step new query wizard.
 *  Data persists across wizard steps but resets on clear(). */
@Injectable({ providedIn: 'root' })
export class WizardService {
  queryType: string = '';
  subject: string = '';
  description: string = '';
  priority: string = 'MEDIUM';
  referenceNumber: string = '';

  setQueryType(type: string): void {
    this.queryType = type;
  }

  setDetails(
    subject: string,
    description: string,
    priority: string,
    referenceNumber: string
  ): void {
    this.subject = subject;
    this.description = description;
    this.priority = priority;
    this.referenceNumber = referenceNumber;
  }

  getSubmissionPayload(): {
    query_type: string;
    subject: string;
    description: string;
    priority: string;
    reference_number?: string;
  } {
    return {
      query_type: this.queryType,
      subject: this.subject,
      description: this.description,
      priority: this.priority,
      ...(this.referenceNumber ? { reference_number: this.referenceNumber } : {}),
    };
  }

  clear(): void {
    this.queryType = '';
    this.subject = '';
    this.description = '';
    this.priority = 'MEDIUM';
    this.referenceNumber = '';
  }
}
