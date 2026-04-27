import {
  Alert, Anchor, Badge, Button, Code, Group, Loader, Stack, Table, Text,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconAlertCircle, IconCheck, IconCircle, IconMinus, IconX,
} from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError } from "../../api";
import {
  listPulls, mergePull, useProject,
  type PullCheckState, type PullRead, type PullsResponse,
} from "./api";

interface Props {
  projectSlug: string;
  // True when the parent Tabs has selected this tab. Drives `enabled`
  // on the query so we don't poll while the user is on the Tasks tab.
  active: boolean;
}

const STATE_COLOR: Record<PullRead["state"], string> = {
  OPEN: "blue", MERGED: "green", CLOSED: "gray",
};
const MERGE_COLOR: Record<PullRead["mergeable"], string> = {
  MERGEABLE: "green", CONFLICTING: "red", UNKNOWN: "gray",
};
const MERGE_LABEL: Record<PullRead["mergeable"], string> = {
  MERGEABLE: "yes", CONFLICTING: "no", UNKNOWN: "unknown",
};
const CHECKS_META: Record<
  PullCheckState, { label: string; color: string; Icon: typeof IconCheck }
> = {
  passing: { label: "All checks passing", color: "green", Icon: IconCheck },
  failing: { label: "Checks failing", color: "red", Icon: IconX },
  pending: { label: "Checks pending", color: "yellow", Icon: IconCircle },
  none: { label: "No checks configured", color: "gray", Icon: IconMinus },
};

function ChecksCell({ state }: { state: PullCheckState }) {
  const { label, color, Icon } = CHECKS_META[state];
  return (
    <Tooltip label={label}>
      <Icon
        size={18}
        color={`var(--mantine-color-${color}-6)`}
        aria-label={label}
      />
    </Tooltip>
  );
}

function formatDate(iso: string): string {
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}

// Pull `detail` out of an ApiError body when the backend includes one
// (gh_failed / gh_timeout). Returns null if absent or shape mismatch.
function errorDetail(err: unknown): string | null {
  if (!(err instanceof ApiError) || !err.body || typeof err.body !== "object") {
    return null;
  }
  const body = err.body as Record<string, unknown>;
  return "detail" in body ? String(body.detail) : null;
}

function MergeButton({
  slug, number, dangerous,
}: { slug: string; number: number; dangerous: boolean }) {
  const qc = useQueryClient();
  const mutation = useMutation({
    mutationFn: () => mergePull(slug, number, "squash"),
    onSuccess: () => {
      notifications.show({ title: "PR merged", message: `#${number} squashed`, color: "green" });
      qc.invalidateQueries({ queryKey: ["projects", slug, "pulls"] });
    },
    onError: (err: unknown) => {
      const detail = errorDetail(err) ?? (err instanceof Error ? err.message : "merge failed");
      notifications.show({ title: "Merge failed", message: detail, color: "red" });
    },
  });
  const onClick = () => {
    if (!dangerous && !window.confirm(`Merge #${number} with squash?`)) return;
    mutation.mutate();
  };
  return (
    <Button size="xs" onClick={onClick} loading={mutation.isPending}>
      Merge
    </Button>
  );
}

export function PullsTab({ projectSlug, active }: Props) {
  const project = useProject(projectSlug);
  const dangerous = project.data?.autonomy_mode === "dangerous";
  const query = useQuery<PullsResponse>({
    queryKey: ["projects", projectSlug, "pulls", { state: "open", include_all: false }],
    queryFn: () => listPulls(projectSlug, { state: "open", include_all: false }),
    enabled: active,
    refetchInterval: active ? 60_000 : false,
  });

  if (query.isLoading) {
    return <Group justify="center" py="md"><Loader size="sm" /></Group>;
  }
  if (query.isError) {
    if (query.error instanceof ApiError && query.error.status === 503) {
      return (
        <Alert color="yellow" title="GitHub CLI not installed">
          <Stack gap="xs">
            <Text size="sm">Install the GitHub CLI to see PRs:</Text>
            <Code block>brew install gh && gh auth login</Code>
          </Stack>
        </Alert>
      );
    }
    const detail = errorDetail(query.error);
    return (
      <Alert icon={<IconAlertCircle size={16} />} color="red" title="Error">
        <Stack gap="xs">
          <Text size="sm">No se pudieron cargar los pull requests.</Text>
          {detail ? <Code block>{detail}</Code> : null}
        </Stack>
      </Alert>
    );
  }

  const data = query.data;
  if (!data) return null;
  if (data.warning === "no_remote") {
    return (
      <Alert color="gray" title="No GitHub remote">
        Configure <Code>git_remote</Code> on this project to see PRs.
      </Alert>
    );
  }
  if (data.warning === "invalid_remote") {
    return (
      <Alert color="gray" title="Remote not on GitHub">
        Project remote is not on GitHub — pulls view supports github.com only.
      </Alert>
    );
  }
  if (data.pulls.length === 0) {
    return (
      <Text c="dimmed" py="md" ta="center">
        No PRs yet — Niwa opens a PR for each task that finishes when this
        project has a <Code>git_remote</Code> configured.
      </Text>
    );
  }

  return (
    <Table withRowBorders verticalSpacing="xs">
      <Table.Thead>
        <Table.Tr>
          <Table.Th>#</Table.Th><Table.Th>Title</Table.Th>
          <Table.Th>State</Table.Th><Table.Th>Mergeable</Table.Th>
          <Table.Th>Checks</Table.Th><Table.Th>Created</Table.Th>
          <Table.Th />
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {data.pulls.map((pr) => (
          <Table.Tr key={pr.number}>
            <Table.Td><Text size="sm" c="dimmed">#{pr.number}</Text></Table.Td>
            <Table.Td>{pr.title}</Table.Td>
            <Table.Td>
              <Badge color={STATE_COLOR[pr.state] ?? "gray"} variant="light">
                {pr.state.toLowerCase()}
              </Badge>
            </Table.Td>
            <Table.Td>
              <Badge color={MERGE_COLOR[pr.mergeable] ?? "gray"} variant="light">
                {MERGE_LABEL[pr.mergeable] ?? "unknown"}
              </Badge>
            </Table.Td>
            <Table.Td><ChecksCell state={pr.checks.state} /></Table.Td>
            <Table.Td>
              <Text size="sm" c="dimmed">{formatDate(pr.created_at)}</Text>
            </Table.Td>
            <Table.Td align="right">
              <Group gap="xs" justify="flex-end" wrap="nowrap">
                {pr.mergeable === "MERGEABLE" ? (
                  <MergeButton
                    slug={projectSlug}
                    number={pr.number}
                    dangerous={dangerous}
                  />
                ) : null}
                <Anchor href={pr.url} target="_blank" rel="noopener noreferrer" size="sm">
                  Open in GitHub
                </Anchor>
              </Group>
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}
