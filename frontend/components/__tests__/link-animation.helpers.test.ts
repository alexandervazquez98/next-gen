/**
 * link-animation.helpers.test.ts
 *
 * Unit tests for the pure helper functions exported from MonitoringConsole.tsx.
 * No DOM, no React — just logic validation following a BDD Given/When/Then pattern.
 *
 * Covers:
 *   - buildLinkConfig  → SC-01-A..E from 02_specs.md
 *   - getNodeRenderConfig → SC-02-A..C from 02_specs.md
 */

import { describe, it, expect } from 'vitest';
import { buildLinkConfig, getNodeRenderConfig } from '../MonitoringConsole';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------
const healthyTarget = { hasCritical: false, hasWarning: false };
const warningTarget = { hasCritical: false, hasWarning: true };
const criticalTarget = { hasCritical: true, hasWarning: false };

const healthySource = { hasCritical: false, hasWarning: false };

// ---------------------------------------------------------------------------
// buildLinkConfig
// ---------------------------------------------------------------------------

describe('buildLinkConfig', () => {
    // SC-01-A
    it('DEPENDS_ON + CRITICAL target → rojo, animDur 0.8s (+20% speed), animate true, no traffic pulse', () => {
        // GIVEN a DEPENDS_ON link with a CRITICAL target
        const link = { relationship: 'DEPENDS_ON' };

        // WHEN buildLinkConfig is called
        const cfg = buildLinkConfig(link, healthySource, criticalTarget);

        // THEN
        expect(cfg.color).toBe('#ef4444');
        expect(cfg.animDur).toBe('0.8s');
        expect(cfg.animate).toBe(true);
        expect(cfg.showTrafficPulse).toBe(false);
        expect(cfg.dashArray).toBe('5, 8');
    });

    // SC-01-B
    it('DEPENDS_ON + WARNING target → naranja, animDur 1.6s (+20% speed)', () => {
        const link = { relationship: 'DEPENDS_ON' };
        const cfg = buildLinkConfig(link, healthySource, warningTarget);

        expect(cfg.color).toBe('#f97316');
        expect(cfg.animDur).toBe('1.6s');
        expect(cfg.animate).toBe(true);
        expect(cfg.showTrafficPulse).toBe(false);
    });

    // SC-01-C
    it('DEPENDS_ON + OK target → azul, animDur 2.4s (+20% speed)', () => {
        const link = { relationship: 'DEPENDS_ON' };
        const cfg = buildLinkConfig(link, healthySource, healthyTarget);

        expect(cfg.animDur).toBe('2.4s');
        expect(cfg.animate).toBe(true);
        expect(cfg.showTrafficPulse).toBe(false);
    });

    // SC-01-D — CONNECTS_TO con target CRITICAL
    it('CONNECTS_TO + CRITICAL target → showTrafficPulse true, color rojo, sin dashArray', () => {
        const link = { relationship: 'CONNECTS_TO' };
        const cfg = buildLinkConfig(link, healthySource, criticalTarget);

        expect(cfg.showTrafficPulse).toBe(true);
        expect(cfg.color).toBe('#ef4444');
        expect(cfg.dashArray).toBeUndefined();
        expect(cfg.animate).toBe(false);
    });

    // SC-01-D — CONNECTS_TO con target OK
    it('CONNECTS_TO + OK target → showTrafficPulse true, color azul', () => {
        const link = { relationship: 'CONNECTS_TO' };
        const cfg = buildLinkConfig(link, healthySource, healthyTarget);

        expect(cfg.showTrafficPulse).toBe(true);
        expect(cfg.animate).toBe(false);
    });

    // SC-01-E
    it('HOSTED_ON → animate false, opacity reducida, sin traffic pulse', () => {
        const link = { relationship: 'HOSTED_ON' };
        const cfg = buildLinkConfig(link, healthySource, criticalTarget);

        expect(cfg.animate).toBe(false);
        expect(cfg.showTrafficPulse).toBe(false);
        expect(cfg.opacity).toBeLessThan(0.6);
        expect(cfg.dashArray).toBe('2, 5');
    });

    // SC-01 — tipo desconocido → fallback válido
    it('Tipo de relación desconocido → retorna config válida (fallback DEPENDS_ON OK)', () => {
        const link = { relationship: 'UNKNOWN_TYPE' };
        const cfg = buildLinkConfig(link, healthySource, healthyTarget);

        expect(cfg).toBeDefined();
        expect(typeof cfg.color).toBe('string');
        expect(typeof cfg.animate).toBe('boolean');
    });
});

// ---------------------------------------------------------------------------
// getNodeRenderConfig
// ---------------------------------------------------------------------------

describe('getNodeRenderConfig', () => {
    // SC-02-A
    it('CRITICAL node → color rojo, showAura true, radio > 6', () => {
        // GIVEN a node with 2 CRITICAL events
        const node = {
            hasCritical: true,
            hasWarning: false,
            events: [{ severity: 'CRITICAL' }, { severity: 'CRITICAL' }],
        };

        // WHEN getNodeRenderConfig is called
        const cfg = getNodeRenderConfig(node);

        // THEN
        expect(cfg.color).toBe('#ef4444');
        expect(cfg.showAura).toBe(true);
        expect(cfg.pixelRadius).toBeGreaterThan(6);
        expect(cfg.fillOpacity).toBe(1);
        expect(cfg.auraRadius).toBeGreaterThan(0);
    });

    // SC-02-B
    it('WARNING node → color amarillo, showAura true', () => {
        const node = {
            hasCritical: false,
            hasWarning: true,
            events: [{ severity: 'WARNING' }],
        };

        const cfg = getNodeRenderConfig(node);

        expect(cfg.color).toBe('#eab308');
        expect(cfg.showAura).toBe(true);
        expect(cfg.fillOpacity).toBe(1);
    });

    // SC-02-C
    it('Healthy node → color azul, showAura false, fillOpacity < 1', () => {
        const node = {
            hasCritical: false,
            hasWarning: false,
            events: [],
        };

        const cfg = getNodeRenderConfig(node);

        expect(cfg.color).toBe('#3b82f6');
        expect(cfg.showAura).toBe(false);
        expect(cfg.fillOpacity).toBeLessThan(1);
        expect(cfg.pixelRadius).toBe(6);
    });

    // Edge case: node sin campo events
    it('Node sin campo events → no lanza error', () => {
        const node = { hasCritical: true, hasWarning: false };
        expect(() => getNodeRenderConfig(node)).not.toThrow();
    });

    // Aura radius escala con cantidad de eventos
    it('CRITICAL node con más eventos → auraRadius mayor', () => {
        const few = getNodeRenderConfig({
            hasCritical: true,
            events: [{ severity: 'CRITICAL' }],
        });
        const many = getNodeRenderConfig({
            hasCritical: true,
            events: [{ severity: 'CRITICAL' }, { severity: 'CRITICAL' }, { severity: 'CRITICAL' }],
        });
        expect(many.auraRadius).toBeGreaterThan(few.auraRadius);
    });
});
