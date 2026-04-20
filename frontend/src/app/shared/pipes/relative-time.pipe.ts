import { Pipe, type PipeTransform } from '@angular/core';

const SECOND = 1_000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const MONTH = 30 * DAY;
const YEAR = 365 * DAY;

@Pipe({ name: 'relativeTime', standalone: true, pure: true })
export class RelativeTimePipe implements PipeTransform {
  transform(value: Date | string | number | null | undefined, now: Date = new Date()): string {
    if (value === null || value === undefined) return '';
    const d = typeof value === 'string' || typeof value === 'number' ? new Date(value) : value;
    if (Number.isNaN(d.getTime())) return typeof value === 'string' ? value : '';

    const delta = now.getTime() - d.getTime();
    const past = delta >= 0;
    const abs = Math.abs(delta);

    const [n, unit] = pick(abs);
    const plural = n === 1 ? unit : `${unit}s`;
    return past ? `${n} ${plural} ago` : `in ${n} ${plural}`;
  }
}

function pick(ms: number): readonly [number, string] {
  if (ms < MINUTE) return [Math.max(1, Math.floor(ms / SECOND)), 'second'];
  if (ms < HOUR) return [Math.floor(ms / MINUTE), 'minute'];
  if (ms < DAY) return [Math.floor(ms / HOUR), 'hour'];
  if (ms < MONTH) return [Math.floor(ms / DAY), 'day'];
  if (ms < YEAR) return [Math.floor(ms / MONTH), 'month'];
  return [Math.floor(ms / YEAR), 'year'];
}
