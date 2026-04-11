import { useMemo } from 'react';
import { createTheme, type MantineColorsTuple } from '@mantine/core';
import { useSettings } from '../api/queries';

/**
 * Genera una tupla de 10 tonos a partir de un color hex,
 * compatible con el sistema de colores de Mantine.
 */
function hexToTuple(hex: string): MantineColorsTuple {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);

  const shades: string[] = [];
  for (let i = 0; i < 10; i++) {
    const mix =
      i < 5
        ? [
            Math.round(r + (255 - r) * (1 - i / 5)),
            Math.round(g + (255 - g) * (1 - i / 5)),
            Math.round(b + (255 - b) * (1 - i / 5)),
          ]
        : [
            Math.round(r * (1 - (i - 5) / 5)),
            Math.round(g * (1 - (i - 5) / 5)),
            Math.round(b * (1 - (i - 5) / 5)),
          ];
    shades.push(`rgb(${mix[0]}, ${mix[1]}, ${mix[2]})`);
  }
  return shades as unknown as MantineColorsTuple;
}

export function useCustomTheme() {
  const { data: settings } = useSettings();

  return useMemo(() => {
    if (!settings) return null;

    const primary = settings['style_primary'];
    const accent = settings['style_accent'];
    const fontFamily = settings['style_font'];
    const radius = settings['style_radius'];

    if (!primary && !accent && !fontFamily && !radius) return null;

    const overrides: Record<string, unknown> = {};

    if (primary) {
      overrides.primaryColor = 'custom';
      overrides.colors = { custom: hexToTuple(primary) };
    }
    if (fontFamily) {
      overrides.fontFamily = fontFamily;
      overrides.headings = { fontFamily };
    }
    if (radius) {
      overrides.defaultRadius = `${radius}px`;
    }

    return createTheme(overrides);
  }, [settings]);
}
