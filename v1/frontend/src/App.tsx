import { Container, Stack, Text, Title } from "@mantine/core";

export default function App() {
  return (
    <Container size="sm" py="xl">
      <Stack gap="sm">
        <Title order={1}>Niwa v1</Title>
        <Text c="dimmed">
          Skeleton landing. Real features land in later PRs per SPEC §9.
        </Text>
      </Stack>
    </Container>
  );
}
