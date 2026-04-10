import { useState, useCallback, useEffect } from 'react';
import {
  Stack,
  Text,
  Group,
  Button,
  Paper,
  ColorInput,
  Select,
  Slider,
  SimpleGrid,
  Badge,
} from '@mantine/core';
import { IconPalette, IconRefresh } from '@tabler/icons-react';
import { notifications } from '@mantine/notifications';
import { useSaveSettings, useSettings } from '../../../shared/api/queries';

const STYLE_PRESETS: Record<string, Record<string, string>> = {
  'Oscuro por defecto': {
    primary: '#4caf50',
    surface: '#1e1e1e',
    background: '#121212',
    text: '#e0e0e0',
    accent: '#81c784',
    border: '#333333',
    error: '#ef5350',
  },
  'Azul medianoche': {
    primary: '#42a5f5',
    surface: '#1a237e',
    background: '#0d1b3e',
    text: '#e3f2fd',
    accent: '#64b5f6',
    border: '#1565c0',
    error: '#ef5350',
  },
  'Bosque verde': {
    primary: '#66bb6a',
    surface: '#1b2e1b',
    background: '#0d1f0d',
    text: '#c8e6c9',
    accent: '#a5d6a7',
    border: '#2e7d32',
    error: '#ef5350',
  },
  'Atardecer cálido': {
    primary: '#ff7043',
    surface: '#2e1a0e',
    background: '#1a0f07',
    text: '#ffe0b2',
    accent: '#ffab91',
    border: '#bf360c',
    error: '#ef5350',
  },
  'Océano': {
    primary: '#26c6da',
    surface: '#0d2b3e',
    background: '#071a2b',
    text: '#b2ebf2',
    accent: '#80deea',
    border: '#00838f',
    error: '#ef5350',
  },
  'Monocromo': {
    primary: '#bdbdbd',
    surface: '#212121',
    background: '#121212',
    text: '#eeeeee',
    accent: '#9e9e9e',
    border: '#424242',
    error: '#ef5350',
  },
  'Retro': {
    primary: '#ffb300',
    surface: '#1e1a14',
    background: '#12100c',
    text: '#fff8e1',
    accent: '#ffd54f',
    border: '#5d4037',
    error: '#e53935',
  },
};

const COLOR_LABELS: Record<string, string> = {
  primary: 'Primario',
  surface: 'Superficie',
  background: 'Fondo',
  text: 'Texto',
  accent: 'Acento',
  border: 'Borde',
  error: 'Error',
};

const FONT_OPTIONS = [
  { value: 'Inter, sans-serif', label: 'Inter' },
  { value: 'JetBrains Mono, monospace', label: 'JetBrains Mono' },
  { value: 'system-ui, sans-serif', label: 'Sistema' },
  { value: "'Fira Code', monospace", label: 'Fira Code' },
  { value: 'Roboto, sans-serif', label: 'Roboto' },
];

const DEFAULT_COLORS = STYLE_PRESETS['Oscuro por defecto'];

export function StylesPanel() {
  const { data: settings } = useSettings();
  const saveSettings = useSaveSettings();

  const [colors, setColors] = useState<Record<string, string>>({ ...DEFAULT_COLORS });
  const [font, setFont] = useState('Inter, sans-serif');
  const [radius, setRadius] = useState(8);

  // Load from settings
  useEffect(() => {
    if (settings) {
      const loaded: Record<string, string> = {};
      for (const key of Object.keys(DEFAULT_COLORS)) {
        if (settings[`style_${key}`]) loaded[key] = settings[`style_${key}`];
      }
      if (Object.keys(loaded).length > 0) {
        setColors((prev) => ({ ...prev, ...loaded }));
      }
      if (settings.style_font) setFont(settings.style_font);
      if (settings.style_radius) setRadius(Number(settings.style_radius) || 8);
    }
  }, [settings]);

  // Apply to CSS variables live
  const applyStyles = useCallback(() => {
    const root = document.documentElement;
    for (const [key, value] of Object.entries(colors)) {
      root.style.setProperty(`--niwa-${key}`, value);
    }
    root.style.setProperty('--niwa-font', font);
    root.style.setProperty('--niwa-radius', `${radius}px`);
  }, [colors, font, radius]);

  useEffect(() => {
    applyStyles();
  }, [applyStyles]);

  const setColor = (key: string, value: string) => {
    setColors((prev) => ({ ...prev, [key]: value }));
  };

  const applyPreset = (presetName: string) => {
    const preset = STYLE_PRESETS[presetName];
    if (preset) {
      setColors({ ...preset });
    }
  };

  const handleSave = async () => {
    const data: Record<string, string> = {};
    for (const [key, value] of Object.entries(colors)) {
      data[`style_${key}`] = value;
    }
    data.style_font = font;
    data.style_radius = String(radius);
    await saveSettings.mutateAsync(data);
    notifications.show({ title: 'Estilos guardados', message: 'Los cambios se han aplicado', color: 'green' });
  };

  const handleReset = () => {
    setColors({ ...DEFAULT_COLORS });
    setFont('Inter, sans-serif');
    setRadius(8);
  };

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Group gap="xs">
          <IconPalette size={20} />
          <Text fw={600} size="lg">Personalización de estilo</Text>
        </Group>
        <Group gap="xs">
          <Button
            variant="light"
            leftSection={<IconRefresh size={16} />}
            onClick={handleReset}
            size="sm"
          >
            Restablecer
          </Button>
          <Button onClick={handleSave} loading={saveSettings.isPending} size="sm">
            Guardar
          </Button>
        </Group>
      </Group>

      {/* Presets */}
      <Paper p="md" radius="md" withBorder>
        <Text fw={500} mb="sm">Temas predefinidos</Text>
        <Group gap="xs">
          {Object.keys(STYLE_PRESETS).map((presetName) => (
            <Badge
              key={presetName}
              size="lg"
              variant="light"
              style={{ cursor: 'pointer' }}
              onClick={() => applyPreset(presetName)}
            >
              {presetName}
            </Badge>
          ))}
        </Group>
      </Paper>

      {/* Color Pickers */}
      <Paper p="md" radius="md" withBorder>
        <Text fw={500} mb="sm">Colores</Text>
        <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }} spacing="sm">
          {Object.entries(COLOR_LABELS).map(([key, label]) => (
            <ColorInput
              key={key}
              label={label}
              value={colors[key] || '#000000'}
              onChange={(v) => setColor(key, v)}
              format="hex"
              swatches={['#4caf50', '#42a5f5', '#ff7043', '#26c6da', '#ffb300', '#bdbdbd', '#ef5350']}
            />
          ))}
        </SimpleGrid>
      </Paper>

      {/* Font & Radius */}
      <Paper p="md" radius="md" withBorder>
        <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
          <Select
            label="Familia de fuente"
            data={FONT_OPTIONS}
            value={font}
            onChange={(v) => setFont(v || 'Inter, sans-serif')}
          />
          <Stack gap="xs">
            <Text size="sm" fw={500}>Radio de borde: {radius}px</Text>
            <Slider
              min={0}
              max={24}
              value={radius}
              onChange={setRadius}
              marks={[
                { value: 0, label: '0' },
                { value: 8, label: '8' },
                { value: 16, label: '16' },
                { value: 24, label: '24' },
              ]}
            />
          </Stack>
        </SimpleGrid>
      </Paper>

      {/* Preview */}
      <Paper p="md" radius="md" withBorder>
        <Text fw={500} mb="sm">Vista previa</Text>
        <Paper
          p="md"
          radius={radius}
          style={{
            backgroundColor: colors.surface,
            border: `1px solid ${colors.border}`,
            fontFamily: font,
          }}
        >
          <Text style={{ color: colors.text }} fw={600} mb="xs">
            Título de ejemplo
          </Text>
          <Text style={{ color: colors.text }} size="sm" mb="xs">
            Este es un texto de ejemplo para previsualizar los estilos.
          </Text>
          <Group gap="xs">
            <Badge style={{ backgroundColor: colors.primary, color: '#fff' }}>
              Primario
            </Badge>
            <Badge style={{ backgroundColor: colors.accent, color: '#000' }}>
              Acento
            </Badge>
            <Badge style={{ backgroundColor: colors.error, color: '#fff' }}>
              Error
            </Badge>
          </Group>
        </Paper>
      </Paper>
    </Stack>
  );
}
