import { useEffect, useState } from 'react';
import { LoadingOverlay } from '@mantine/core';
import { checkAuth } from '../shared/api/client';
import { useAppStore } from '../shared/stores/app';
import { AppShell } from '../shared/components/AppShell';
import { LoginPage } from '../shared/components/LoginPage';
import { AppRouter } from './Router';

export function App() {
  const { authenticated, setAuthenticated } = useAppStore();
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    checkAuth()
      .then((ok) => setAuthenticated(ok))
      .finally(() => setChecking(false));
  }, [setAuthenticated]);

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
