import { daysBetween, formatDate, formatDayAndDate, isoDate } from '@/utils/dates';

describe('dates', () => {
  it('formats contract dates for people', () => {
    expect(formatDate('2026-11-02')).toBe('2 Nov 2026');
    expect(formatDayAndDate('2026-11-12')).toBe('Thu, 12 Nov');
    expect(formatDayAndDate('2026-11-15')).toBe('Sun, 15 Nov');
  });

  it('uses the local calendar day', () => {
    expect(isoDate(new Date(2026, 0, 5, 23, 30))).toBe('2026-01-05');
  });

  it('counts whole days across a month and a time change', () => {
    expect(daysBetween('2026-10-20', '2026-11-02')).toBe(13);
    expect(daysBetween('2026-11-10', '2026-11-10')).toBe(0);
  });
});
