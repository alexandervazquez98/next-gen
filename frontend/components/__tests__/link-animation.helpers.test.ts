/**
 * link-animation.helpers.test.ts
 *
 * Unit tests for the pure helper functions exported from MonitoringConsole.tsx.
 * No DOM, no React — just logic validation following a BDD Given/When/Then pattern.
 *
 * Covers:
 *   - buildLinkConfig  → SC-01-A..F from 02_specs.md
 *   - getNodeRenderConfig → SC-02-A..C from 02_specs.md
 */

import { describe, it, expect } from 'vitest';
import { buildLinkConfig, getNodeRenderConfig } from '../MonitoringConsole';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------
const healthyNode  = { hasCritical: false, hasWarning: false };
const warningNode  = { hasCritical: false, hasWarning: true  };
const criticalNode = { hasCritical: true,  hasWarning: false };

// ---------------------------------------------------------------------------
// buildLinkConfig
// ---------------------------------------------------------------------------

describe('buildLinkConfig', () => {
    // SC-01-A
    it('DEPENDS_ON + CRITICAL target → rojo, animDur 0.8s, animate true, no traffic pulse', () => {
        // GIVEN a DEPENDS_ON link with a CRITICAL target and healthy source
        const link = { relationship: 'DEPENDS_ON' };

        // WHEN buildLinkConfig is called
        const cfg = buildLinkConfig(link, healthyNode, criticalNode);

        // THEN
        expect(cfg.color).toBe('#ef4444');
        expect(cfg.animDur).toBe('0.8s');
        expect(cfg.animate).toBe(true);
        expect(cfg.showTrafficPulse).toBe(false);
        expect(cfg.dashArray).toBe('6, 8');
        expect(cfg.weight).toBe(5);
    });

    // SC-01-A2 — source CRITICAL (línea desde CI alarmado hacia root)
    it('DEPENDS_ON + CRITICAL source + healthy target → rojo, igual que target CRITICAL', () => {
        // GIVEN a DEPENDS_ON link where the SOURCE is the alarmed CI
        const link = { relationship: 'DEPENDS_ON' };

        // WHEN
        const cfg = buildLinkConfig(link, criticalNode, healthyNode);

        // THEN the line should be red — not grey
        expect(cfg.color).toBe('#ef4444');
        expect(cfg.animDur).toBe('0.8s');
        expect(cfg.weight).toBe(5);
    });

    // SC-01-B
    it('DEPENDS_ON + WARNING target → amarillo, animDur 1.6s', () => {
        const link = { relationship: 'DEPENDS_ON' };
        const cfg = buildLinkConfig(link, healthyNode, warningNode);

        expect(cfg.color).toBe('#f59e0b');
        expect(cfg.animDur).toBe('1.6s');
        expect(cfg.animate).toBe(true);
        expect(cfg.showTrafficPulse).toBe(false);
        expect(cfg.weight).toBe(4);
    });

    // SC-01-C
    it('DEPENDS_ON + OK target + OK source → verde, animDur 2.4s, weight 3', () => {
        const link = { relationship: 'DEPENDS_ON' };
        const cfg = buildLinkConfig(link, healthyNode, healthyNode);

        expect(cfg.color).toBe('#10b981');
        expect(cfg.animDur).toBe('2.4s');
        expect(cfg.animate).toBe(true);
        expect(cfg.showTrafficPulse).toBe(false);
        expect(cfg.weight).toBe(3);
    });

    // SC-01-D — CONNECTS_TO con CRITICAL en cualquier extremo
    it('CONNECTS_TO + CRITICAL target → static, showTrafficPulse false, color rojo', () => {
        const link = { relationship: 'CONNECTS_TO' };
        const cfg = buildLinkConfig(link, healthyNode, criticalNode);

        expect(cfg.showTrafficPulse).toBe(false);
        expect(cfg.opacity).toBe(0.6);
        expect(cfg.color).toBe('#ef4444');
        expect(cfg.dashArray).toBeUndefined();
        expect(cfg.animate).toBe(false);
        expect(cfg.weight).toBe(5);
    });

    // SC-01-D2
    it('CONNECTS_TO + OK → static, showTrafficPulse false, color verde', () => {
        const link = { relationship: 'CONNECTS_TO' };
        const cfg = buildLinkConfig(link, healthyNode, healthyNode);

        expect(cfg.showTrafficPulse).toBe(false);
        expect(cfg.opacity).toBe(0.6);
        expect(cfg.color).toBe('#10b981');
        expect(cfg.animate).toBe(false);
        expect(cfg.weight).toBe(3);
    });

    // SC-01-E
    it('HOSTED_ON healthy → animate false, opacity baja, sin traffic pulse, gris', () => {
        const link = { relationship: 'HOSTED_ON' };
        const cfg = buildLinkConfig(link, healthyNode, healthyNode);

        expect(cfg.animate).toBe(false);
        expect(cfg.showTrafficPulse).toBe(false);
        expect(cfg.opacity).toBeLessThan(0.6);
        expect(cfg.dashArray).toBe('2, 5');
        expect(cfg.weight).toBeLessThan(2);
    });

    // SC-01-E2 — HOSTED_ON con CRITICAL source → debe reflejar rojo
    it('HOSTED_ON + CRITICAL source → color rojo, weight mayor', () => {
        const link = { relationship: 'HOSTED_ON' };
        const cfg = buildLinkConfig(link, criticalNode, healthyNode);

        expect(cfg.color).toBe('#ef4444');
        expect(cfg.weight).toBeGreaterThan(1.5);
    });

    // SC-01 — tipo desconocido → fallback válido
    it('Tipo de relación desconocido → retorna config válida (fallback DEPENDS_ON OK)', () => {
        const link = { relationship: 'UNKNOWN_TYPE' };
        const cfg = buildLinkConfig(link, healthyNode, healthyNode);

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
