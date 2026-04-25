import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Code,
  Group,
  List,
  Loader,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { IconAlertCircle, IconPlus } from "@tabler/icons-react";
import { Link } from "react-router-dom";

import { useProjects } from "./api";
import { ProjectCreateModal } from "./ProjectCreateModal";

export function ProjectList() {
  const [modalOpen, setModalOpen] = useState(false);
  const query = useProjects();
  const isEmpty = !query.isLoading && !query.isError && query.data && query.data.length === 0;

  return (
    <Stack gap="md">
      <Group justify="space-between" align="center">
        <Title order={2}>Projects</Title>
        <Button
          leftSection={<IconPlus size={16} />}
          onClick={() => setModalOpen(true)}
        >
          Nuevo proyecto
        </Button>
      </Group>

      {query.isLoading ? (
        <Group justify="center" py="xl">
          <Loader />
        </Group>
      ) : query.isError ? (
        <Alert icon={<IconAlertCircle size={16} />} color="red" title="Error">
          No se pudieron cargar los proyectos.
        </Alert>
      ) : isEmpty ? (
        <Card withBorder shadow="sm" padding="lg">
          <Stack gap="md">
            <Title order={3}>👋 Welcome to Niwa</Title>
            <Text>
              Niwa runs Claude Code on your local git repos. To get started:
            </Text>
            <List type="ordered" spacing="sm">
              <List.Item>
                <Stack gap="xs">
                  <Text>
                    Clone a repo to your machine if you haven't yet:
                  </Text>
                  <Code block>
{`git clone https://github.com/you/your-repo
cd your-repo`}
                  </Code>
                </Stack>
              </List.Item>
              <List.Item>
                <Stack gap="xs">
                  <Text>Create a project pointing at it.</Text>
                  <Group>
                    <Button
                      leftSection={<IconPlus size={16} />}
                      onClick={() => setModalOpen(true)}
                    >
                      New project
                    </Button>
                  </Group>
                </Stack>
              </List.Item>
            </List>
            <Text c="dimmed" size="sm">
              Need more detail? See{" "}
              <Text component={Link} to="/help" td="underline" inherit>
                Help
              </Text>{" "}
              for the full onboarding guide.
            </Text>
          </Stack>
        </Card>
      ) : (
        <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }} spacing="md">
          {query.data?.map((p) => (
            <Card
              key={p.id}
              component={Link}
              to={`/projects/${p.slug}`}
              withBorder
              shadow="sm"
              padding="md"
              style={{ textDecoration: "none" }}
            >
              <Stack gap="xs">
                <Text fw={600}>{p.name}</Text>
                <Group gap="xs">
                  <Badge variant="light">{p.kind}</Badge>
                  <Badge
                    variant="light"
                    color={p.autonomy_mode === "dangerous" ? "red" : "green"}
                  >
                    {p.autonomy_mode}
                  </Badge>
                </Group>
                <Text c="dimmed" size="xs">
                  /{p.slug}
                </Text>
              </Stack>
            </Card>
          ))}
        </SimpleGrid>
      )}

      <ProjectCreateModal opened={modalOpen} onClose={() => setModalOpen(false)} />
    </Stack>
  );
}
