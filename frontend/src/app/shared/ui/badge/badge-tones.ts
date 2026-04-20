import type { Priority, QueryStatus } from '../../models/query';
import type { BadgeTone } from './badge';

export function statusTone(status: QueryStatus): BadgeTone {
  switch (status) {
    case 'Open':
      return 'info';
    case 'In Progress':
      return 'primary';
    case 'Awaiting Vendor':
      return 'warn';
    case 'Resolved':
      return 'success';
    case 'Breached':
      return 'error';
  }
}

export function priorityTone(priority: Priority): BadgeTone {
  switch (priority) {
    case 'Critical':
      return 'error';
    case 'High':
      return 'warn';
    case 'Medium':
      return 'info';
    case 'Low':
      return 'neutral';
  }
}
