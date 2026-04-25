import { AppShell as MantineAppShell, Container, Group, Title, UnstyledButton } from "@mantine/core";
import { IconHelpCircle } from "@tabler/icons-react";
import { Link, Outlet } from "react-router-dom";

// Minimal shell: fixed header with product name + Help link, main area
// renders the matched route via <Outlet/>. Help arrived in PR-V1-28.
export function AppShell() {
  return (
    <MantineAppShell header={{ height: 56 }} padding="md">
      <MantineAppShell.Header>
        <Container size="lg" h="100%" style={{ display: "flex", alignItems: "center" }}>
          <Group justify="space-between" w="100%">
            <Title order={3}>Niwa v1</Title>
            <UnstyledButton component={Link} to="/help" aria-label="Help">
              <Group gap={4}>
                <IconHelpCircle size={18} />
                <span>Help</span>
              </Group>
            </UnstyledButton>
          </Group>
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
