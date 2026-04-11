import React from 'react';
import ReactDOM from 'react-dom/client';
import { MantineProvider, mergeThemeOverrides } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import { theme as baseTheme } from './app/theme';
import { App } from './app/App';
import { useCustomTheme } from './shared/hooks/useCustomTheme';
import '@mantine/core/styles.css';
import '@mantine/notifications/styles.css';
import '@mantine/charts/styles.css';
import '@mantine/dates/styles.css';
import '@mantine/code-highlight/styles.css';
import '@mantine/dropzone/styles.css';
import '@mantine/spotlight/styles.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
  },
});

function ThemedApp() {
  const customTheme = useCustomTheme();
  const finalTheme = customTheme
    ? mergeThemeOverrides(baseTheme, customTheme)
    : baseTheme;

  return (
    <MantineProvider theme={finalTheme} defaultColorScheme="dark">
      <Notifications position="top-right" />
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </MantineProvider>
  );
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemedApp />
    </QueryClientProvider>
  </React.StrictMode>,
);
