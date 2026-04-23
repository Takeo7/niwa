import { Alert, Badge, Button, Group, Skeleton, Stack, Table, Title } from "@mantine/core";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch, type ReadinessResponse } from "../api";

// `/system` is a read-only health snapshot (SPEC §7). No `refetchInterval`:
// user hits Refresh to re-check (brief fences polling).
const READINESS_KEY = ["readiness"] as const;

export function useReadiness() {
  return useQuery<ReadinessResponse>({
    queryKey: READINESS_KEY,
    queryFn: () => apiFetch<ReadinessResponse>("/readiness"),
  });
}

interface Row {
  label: string;
  ok: boolean;
  details: string;
}

function buildRows(data: ReadinessResponse): Row[] {
  const d = data.details;
  return [
    {
      label: "Database",
      ok: data.db_ok,
      details: data.db_ok ? d.db.path : d.db.error ?? "database unreachable",
    },
    {
      label: "Claude CLI",
      ok: data.claude_cli_ok,
      details: data.claude_cli_ok
        ? d.claude_cli.path ?? ""
        : "claude binary not on PATH — set [claude].cli in ~/.niwa/config.toml",
    },
    {
      label: "git",
      ok: data.git_ok,
      details: data.git_ok ? d.git.version ?? "" : d.git.error ?? "git not available",
    },
    {
      label: "gh",
      ok: data.gh_ok,
      details: data.gh_ok ? "installed" : d.gh.hint ?? d.gh.error ?? "gh not available",
    },
  ];
}

export function SystemRoute() {
  const qc = useQueryClient();
  const { data, isLoading, isError, error, isFetching } = useReadiness();

  return (
    <Stack gap="md">
      <Group justify="space-between" align="center">
        <Title order={2}>System readiness</Title>
        <Button
          variant="default"
          onClick={() => qc.invalidateQueries({ queryKey: READINESS_KEY })}
          loading={isFetching}
          aria-label="Refresh readiness checks"
        >
          Refresh
        </Button>
      </Group>

      {isLoading && <Skeleton height={160} />}

      {isError && (
        <Alert color="red" title="Readiness check failed">
          {(error as Error | null)?.message ?? "unknown error"}
        </Alert>
      )}

      {data && (
        <Table striped withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Check</Table.Th>
              <Table.Th>Status</Table.Th>
              <Table.Th>Details</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {buildRows(data).map((row) => (
              <Table.Tr key={row.label}>
                <Table.Td>{row.label}</Table.Td>
                <Table.Td>
                  {row.ok ? <Badge color="green">OK</Badge> : <Badge color="red">Missing</Badge>}
                </Table.Td>
                <Table.Td>{row.details}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  );
}
