import { useEffect, useState } from 'react';
import { LoadingOverlay } from '@mantine/core';
import { checkAuth } from '../shared/api/client';
import { useAppStore } from '../shared/stores/app';
import { AppShell } from '../shared/components/AppShell';
import { LoginPage } from '../shared/components/LoginPage';
import { AppRouter } from './Router';
import { useSettings } from '../shared/api/queries';

const CSS_VAR_KEYS = [
  'primary', 'surface', 'background', 'text', 'accent', 'border', 'error',
] as const;

export function App() {
  const { authenticated, setAuthenticated } = useAppStore();
  const [checking, setChecking] = useState(true);
  const { data: settings } = useSettings();

  useEffect(() => {
    checkAuth()
      .then((ok) => setAuthenticated(ok))
      .finally(() => setChecking(false));
  }, [setAuthenticated]);

  // Inyectar variables CSS personalizadas en :root
  useEffect(() => {
    if (!settings) return;
    const root = document.documentElement;
    for (const key of CSS_VAR_KEYS) {
      const val = settings[`style_${key}`];
      if (val) root.style.setProperty(`--niwa-${key}`, val);
    }
    const font = settings['style_font'];
    if (font) root.style.setProperty('--niwa-font', font);
    const radius = settings['style_radius'];
    if (radius) root.style.setProperty('--niwa-radius', `${radius}px`);
  }, [settings]);

  if (checking) {
    return <LoadingOverlay visible />;
  }

  if (!authenticated) {
    return <LoginPage onSuccess={() => setAuthenticated(true)} />;
  }

  return (
    <AppShell>
      <AppRouter />
    </AppShell>
  );
}
