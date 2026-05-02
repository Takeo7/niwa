import {
  Alert,
  Badge,
  Button,
  Code,
  Group,
  PasswordInput,
  Stack,
  Table,
  Tabs,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useEffect, useState } from "react";

import {
  ApiToken,
  ApiTokenCreated,
  AuditEvent,
  AuthStatus,
  Metrics,
  createTokenApi,
  getAuthStatus,
  getMe,
  getMetrics,
  killSwitch,
  listAuditEvents,
  listTokens,
  login,
  logout,
  revokeTokenApi,
} from "../../api";

const ALL_SCOPES = ["read", "task:create", "task:write", "merge", "deploy", "admin"];

export function AdminPanel() {
  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null);
  const [authed, setAuthed] = useState<boolean>(false);
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    async function loadAuth() {
      try {
        const status = await getAuthStatus();
        if (!active) return;
        setAuthStatus(status);
        if (!status.enabled) {
          setAuthed(true);
          return;
        }
        try {
          await getMe();
          if (active) setAuthed(true);
        } catch {
          if (active) setAuthed(false);
        }
      } catch {
        if (!active) return;
        setAuthStatus({ enabled: false });
        setAuthed(true);
      }
    }
    loadAuth();
    return () => {
      active = false;
    };
  }, []);

  if (authStatus === null) return <div>Loading…</div>;

  const requiresLogin = authStatus.enabled && !authed;

  if (requiresLogin) {
    return (
      <Stack maw={400}>
        <Title order={2}>Login</Title>
        <PasswordInput
          label="Password"
          value={password}
          onChange={(e) => setPassword(e.currentTarget.value)}
        />
        {loginError && <Alert color="red">{loginError}</Alert>}
        <Button
          onClick={async () => {
            try {
              await login(password);
              setAuthed(true);
              setLoginError(null);
            } catch (err: unknown) {
              setLoginError("Invalid password");
            }
          }}
        >
          Sign in
        </Button>
      </Stack>
    );
  }

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>Admin</Title>
        {authStatus.enabled && (
          <Button
            variant="subtle"
            onClick={async () => {
              await logout();
              setAuthed(false);
            }}
          >
            Logout
          </Button>
        )}
      </Group>
      {!authStatus.enabled && (
        <Alert color="yellow" title="Auth disabled">
          No password configured. Run <Code>niwa-executor set-password</Code> to enable auth.
        </Alert>
      )}
      <Tabs defaultValue="metrics">
        <Tabs.List>
          <Tabs.Tab value="metrics">Metrics</Tabs.Tab>
          <Tabs.Tab value="tokens">API Tokens</Tabs.Tab>
          <Tabs.Tab value="audit">Audit Log</Tabs.Tab>
          <Tabs.Tab value="ops">Ops</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="metrics" pt="md"><MetricsTab /></Tabs.Panel>
        <Tabs.Panel value="tokens" pt="md"><TokensTab /></Tabs.Panel>
        <Tabs.Panel value="audit" pt="md"><AuditTab /></Tabs.Panel>
        <Tabs.Panel value="ops" pt="md"><OpsTab /></Tabs.Panel>
      </Tabs>
    </Stack>
  );
}

function MetricsTab() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  useEffect(() => {
    getMetrics().then(setMetrics);
  }, []);
  if (!metrics) return <div>Loading metrics…</div>;
  return (
    <Stack>
      <Group>
        <Badge size="lg" variant="light">Projects: {metrics.total_projects}</Badge>
        <Badge size="lg" variant="light">Tasks: {metrics.total_tasks}</Badge>
        <Badge size="lg" variant="light" color="orange">Active runs: {metrics.active_runs}</Badge>
      </Group>
      <Title order={4}>Tasks by status</Title>
      <Table>
        <Table.Thead>
          <Table.Tr><Table.Th>Status</Table.Th><Table.Th>Count</Table.Th></Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {Object.entries(metrics.tasks_by_status).map(([s, c]) => (
            <Table.Tr key={s}><Table.Td>{s}</Table.Td><Table.Td>{c}</Table.Td></Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}

function TokensTab() {
  const [tokens, setTokens] = useState<ApiToken[]>([]);
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(["read"]);
  const [created, setCreated] = useState<ApiTokenCreated | null>(null);

  const refresh = () => listTokens().then(setTokens).catch(() => setTokens([]));
  useEffect(() => { refresh(); }, []);

  return (
    <Stack>
      <Title order={4}>Create token</Title>
      <Group>
        <TextInput
          label="Name"
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
        />
        <Group>
          {ALL_SCOPES.map((s) => (
            <label key={s} style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <input
                type="checkbox"
                checked={scopes.includes(s)}
                onChange={(e) =>
                  setScopes(
                    e.currentTarget.checked
                      ? [...scopes, s]
                      : scopes.filter((x) => x !== s),
                  )
                }
              />
              {s}
            </label>
          ))}
        </Group>
        <Button
          disabled={!name || scopes.length === 0}
          onClick={async () => {
            const r = await createTokenApi(name, scopes);
            setCreated(r);
            setName("");
            refresh();
          }}
        >
          Create
        </Button>
      </Group>
      {created && (
        <Alert color="green" title="Token created — copy now, shown only once">
          <Code>{created.token}</Code>
        </Alert>
      )}
      <Title order={4}>Existing tokens</Title>
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Name</Table.Th>
            <Table.Th>Scopes</Table.Th>
            <Table.Th>Created</Table.Th>
            <Table.Th>Last used</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {tokens.map((t) => (
            <Table.Tr key={t.id}>
              <Table.Td>{t.name}</Table.Td>
              <Table.Td>{t.scopes}</Table.Td>
              <Table.Td>{new Date(t.created_at).toLocaleString()}</Table.Td>
              <Table.Td>{t.last_used_at ? new Date(t.last_used_at).toLocaleString() : "—"}</Table.Td>
              <Table.Td>
                <Button
                  size="xs"
                  color="red"
                  variant="subtle"
                  onClick={async () => {
                    await revokeTokenApi(t.id);
                    refresh();
                  }}
                >
                  Revoke
                </Button>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}

function AuditTab() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  useEffect(() => {
    listAuditEvents({ limit: 100 }).then(setEvents).catch(() => setEvents([]));
  }, []);
  return (
    <Stack>
      <Title order={4}>Recent events</Title>
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>When</Table.Th>
            <Table.Th>Actor</Table.Th>
            <Table.Th>Action</Table.Th>
            <Table.Th>Target</Table.Th>
            <Table.Th>IP</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {events.map((e) => (
            <Table.Tr key={e.id}>
              <Table.Td>{new Date(e.created_at).toLocaleString()}</Table.Td>
              <Table.Td>{e.actor_type}{e.actor_id ? `:${e.actor_id}` : ""}</Table.Td>
              <Table.Td><Code>{e.action}</Code></Table.Td>
              <Table.Td>{e.target_type ? `${e.target_type}#${e.target_id}` : "—"}</Table.Td>
              <Table.Td>{e.ip_address ?? "—"}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}

function OpsTab() {
  const [result, setResult] = useState<string | null>(null);
  return (
    <Stack maw={500}>
      <Title order={4}>Kill switch</Title>
      <Alert color="red" title="Danger">
        Cancels all queued, running and waiting tasks. Use only for incidents.
      </Alert>
      <Alert color="blue" title="Operator checks">
        <Stack gap={4}>
          <Text size="sm">Run <Code>niwa-executor doctor</Code> before exposing Niwa.</Text>
          <Text size="sm">Run <Code>make smoke</Code> after upgrades or config changes.</Text>
        </Stack>
      </Alert>
      <Button
        color="red"
        onClick={async () => {
          if (!window.confirm("Cancel all active tasks?")) return;
          const r = await killSwitch();
          setResult(`Cancelled ${r.cancelled_tasks} tasks (queued ${r.queued_tasks_cancelled}, waiting ${r.waiting_tasks_cancelled}, running ${r.running_tasks_marked})`);
        }}
      >
        Trigger kill switch
      </Button>
      {result && <Alert color="green">{result}</Alert>}
    </Stack>
  );
}
