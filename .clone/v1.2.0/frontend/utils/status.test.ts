import { describe, it, expect } from 'vitest';
import { getStatusColorHex, getStatusClasses, STATUS_COLORS } from '../utils/status';

describe('getStatusColorHex', () => {
  it('returns UNKNOWN color for null/undefined status', () => {
    expect(getStatusColorHex(null)).toBe(STATUS_COLORS.UNKNOWN);
    expect(getStatusColorHex(undefined)).toBe(STATUS_COLORS.UNKNOWN);
  });

  it('returns correct color for CRITICAL status', () => {
    expect(getStatusColorHex('CRITICAL')).toBe(STATUS_COLORS.CRITICAL);
    expect(getStatusColorHex('critical')).toBe(STATUS_COLORS.CRITICAL);
  });

  it('returns correct color for WARNING status', () => {
    expect(getStatusColorHex('WARNING')).toBe(STATUS_COLORS.WARNING);
    expect(getStatusColorHex('warning')).toBe(STATUS_COLORS.WARNING);
  });

  it('returns OK color for both OK and ACTIVE status', () => {
    expect(getStatusColorHex('OK')).toBe(STATUS_COLORS.OK);
    expect(getStatusColorHex('ACTIVE')).toBe(STATUS_COLORS.OK);
    expect(getStatusColorHex('ok')).toBe(STATUS_COLORS.OK);
  });

  it('returns UNKNOWN for unrecognized status', () => {
    expect(getStatusColorHex('FOOBAR')).toBe(STATUS_COLORS.UNKNOWN);
  });
});

describe('getStatusClasses', () => {
  it('returns neutral classes for null/undefined status', () => {
    expect(getStatusClasses(null)).toBe('text-neutral-500 bg-neutral-500/10 border-neutral-500/20');
    expect(getStatusClasses(undefined)).toBe('text-neutral-500 bg-neutral-500/10 border-neutral-500/20');
  });

  it('returns correct classes for CRITICAL', () => {
    expect(getStatusClasses('CRITICAL')).toBe('text-red-500 bg-red-500/10 border-red-500/20');
  });

  it('returns correct classes for WARNING', () => {
    expect(getStatusClasses('WARNING')).toBe('text-yellow-500 bg-yellow-500/10 border-yellow-500/20');
  });

  it('returns emerald classes for OK and ACTIVE', () => {
    expect(getStatusClasses('OK')).toBe('text-emerald-500 bg-emerald-500/10 border-emerald-500/20');
    expect(getStatusClasses('ACTIVE')).toBe('text-emerald-500 bg-emerald-500/10 border-emerald-500/20');
  });

  it('returns neutral classes for unrecognized status', () => {
    expect(getStatusClasses('UNKNOWN_STATUS')).toBe('text-neutral-500 bg-neutral-500/10 border-neutral-500/20');
  });
});
