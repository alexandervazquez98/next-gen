import { describe, expect, it } from 'vitest';
import { formatMetricValue } from './metricFormatting';

describe('formatMetricValue', () => {
	it('rounds millisecond metric values to two decimals for display only', () => {
		expect(formatMetricValue(0.20000000000000018, 'ms')).toBe('0.20');
		expect(formatMetricValue('3.486', 'ms')).toBe('3.49');
	});

	it('keeps non-ms values unchanged', () => {
		expect(formatMetricValue(1, undefined)).toBe('1');
		expect(formatMetricValue('OK', undefined)).toBe('OK');
	});
});
