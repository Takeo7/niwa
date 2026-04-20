import { AppShell as MantineAppShell, Container, Title } from "@mantine/core";
import { Outlet } from "react-router-dom";

// Minimal shell: fixed header with product name, main area renders the
// matched route via <Outlet/>. No navbar/aside yet — /system arrives in a
// later PR (SPEC §7).
export function AppShell() {
  return (
    <MantineAppShell header={{ height: 56 }} padding="md">
      <MantineAppShell.Header>
        <Container size="lg" h="100%" style={{ display: "flex", alignItems: "center" }}>
          <Title order={3}>Niwa v1</Title>
        </Container>
      </MantineAppShell.Header>
      <MantineAppShell.Main>
        <Container size="lg" py="md">
          <Outlet />
        </Container>
      </MantineAppShell.Main>
    </MantineAppShell>
  );
}
