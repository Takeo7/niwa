import type { MantineColor } from '@mantine/core';
import type { CanonicalRiskLevel } from '../../shared/types';

// Canonical risk palette per the PR-05 SPEC.  Kept sober on purpose
// (editorial product register) — the only hot note is ``critical``
// in red; the rest modulate weight, not hue.
const CANONICAL_COLORS: Record<CanonicalRiskLevel, MantineColor> = {
  low: 'gray',
  medium: 'yellow',
  high: 'orange',
  critical: 'red',
};

const CANONICAL_LABELS: Record<CanonicalRiskLevel, string> = {
  low: 'Bajo',
  medium: 'Medio',
  high: 'Alto',
  critical: 'Crítico',
};

const CANONICAL_SET = new Set<CanonicalRiskLevel>([
  'low', 'medium', 'high', 'critical',
]);

export function isCanonicalRisk(value: string): value is CanonicalRiskLevel {
  return CANONICAL_SET.has(value as CanonicalRiskLevel);
}

/** Map an approval risk_level to a ``{color, label, canonical}``
 *  triple.  Bug 9 (PR-06) notes that ``risk_level`` is NOT validated
 *  on insert, so the UI must tolerate anything the backend stores.
 *
 *  For non-canonical values we return ``canonical: false`` and a
 *  neutral grey so the drift is visible (badge variant can show it
 *  as outline instead of light to further flag the anomaly), but
 *  the string itself is rendered verbatim rather than hidden.
 */
export function riskStyle(risk: string | null): {
  color: MantineColor;
  label: string;
  canonical: boolean;
} {
  if (!risk) {
    return { color: 'gray', label: '—', canonical: false };
  }
  const normalised = risk.toLowerCase();
  if (isCanonicalRisk(normalised)) {
    return {
      color: CANONICAL_COLORS[normalised],
      label: CANONICAL_LABELS[normalised],
      canonical: true,
    };
  }
  return { color: 'gray', label: risk, canonical: false };
}
