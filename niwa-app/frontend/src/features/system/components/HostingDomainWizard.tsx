import { useState, useEffect } from 'react';
import {
  Card,
  Stack,
  Group,
  Title,
  Text,
  TextInput,
  Button,
  Badge,
  CopyButton,
  Tooltip,
  ActionIcon,
  Code,
  Divider,
  Alert,
  Loader,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import {
  IconCircleCheck,
  IconCircleX,
  IconCopy,
  IconCheck,
  IconInfoCircle,
  IconRefresh,
} from '@tabler/icons-react';
import {
  useHostingStatus,
  useSaveService,
  type HostingStatus,
} from '../../../shared/api/queries';

export function HostingDomainWizard() {
  const status = useHostingStatus();
  const saveService = useSaveService();
  const [domainInput, setDomainInput] = useState('');

  // Keep the input seeded with the persisted value when it arrives.
  useEffect(() => {
    if (status.data?.domain && domainInput === '') {
      setDomainInput(status.data.domain);
    }
  }, [status.data?.domain, domainInput]);

  async function handleSaveDomain() {
    const cleaned = domainInput.trim().toLowerCase();
    if (!cleaned) {
      notifications.show({
        title: 'Dominio vacío',
        message: 'Escribe un dominio antes de guardar.',
        color: 'red',
      });
      return;
    }
    try {
      await saveService.mutateAsync({
        id: 'hosting',
        values: { 'svc.hosting.domain': cleaned },
      });
      notifications.show({
        title: 'Dominio guardado',
        message: cleaned,
        color: 'green',
      });
      status.refetch();
    } catch (err) {
      notifications.show({
        title: 'Error al guardar',
        message: err instanceof Error ? err.message : 'Fallo desconocido',
        color: 'red',
      });
    }
  }

  return (
    <Card withBorder>
      <Stack gap="md">
        <Group justify="space-between">
          <Title order={4}>Configura tu dominio</Title>
          <Button
            variant="subtle"
            size="compact-sm"
            leftSection={<IconRefresh size={14} />}
            onClick={() => status.refetch()}
            loading={status.isFetching}
          >
            Verificar
          </Button>
        </Group>

        <Alert color="blue" variant="light" icon={<IconInfoCircle size={16} />}>
          Este asistente asume que usas <strong>Cloudflare con el proxy
          naranja ON</strong>. Cloudflare termina HTTPS y reenvía tráfico a
          este servidor por HTTP. Si usas otro DNS, sigue las mismas
          instrucciones pero gestiona el TLS por tu cuenta.
        </Alert>

        <Step1PublicIp status={status.data} isLoading={status.isLoading} />
        <Divider />
        <Step2DnsRecords status={status.data} />
        <Divider />
        <Step3Domain
          domainInput={domainInput}
          setDomainInput={setDomainInput}
          onSave={handleSaveDomain}
          saving={saveService.isPending}
          status={status.data}
        />
        <Divider />
        <Step4Verify status={status.data} isLoading={status.isLoading} />
      </Stack>
    </Card>
  );
}

function StatusLine({ ok, label }: { ok: boolean | null; label: React.ReactNode }) {
  return (
    <Group gap="xs" wrap="nowrap">
      {ok === null ? (
        <Loader size="xs" />
      ) : ok ? (
        <IconCircleCheck size={18} color="var(--mantine-color-green-6)" />
      ) : (
        <IconCircleX size={18} color="var(--mantine-color-red-6)" />
      )}
      <Text size="sm">{label}</Text>
    </Group>
  );
}

function CopyRow({ label, value }: { label: string; value: string }) {
  return (
    <Group gap="xs" wrap="nowrap">
      <Text size="xs" c="dimmed" w={70}>
        {label}
      </Text>
      <Code style={{ flex: 1, wordBreak: 'break-all' }}>{value}</Code>
      <CopyButton value={value} timeout={1500}>
        {({ copied, copy }) => (
          <Tooltip label={copied ? 'Copiado' : 'Copiar'} withArrow>
            <ActionIcon variant="subtle" color="gray" onClick={copy}>
              {copied ? <IconCheck size={14} /> : <IconCopy size={14} />}
            </ActionIcon>
          </Tooltip>
        )}
      </CopyButton>
    </Group>
  );
}

function Step1PublicIp({
  status,
  isLoading,
}: {
  status: HostingStatus | undefined;
  isLoading: boolean;
}) {
  return (
    <Stack gap="xs">
      <Text fw={500}>
        <Badge mr="xs" size="sm">
          1
        </Badge>
        IP pública de este servidor
      </Text>
      {isLoading ? (
        <Loader size="xs" />
      ) : status?.public_ip ? (
        <CopyRow label="IPv4" value={status.public_ip} />
      ) : (
        <Alert color="yellow" variant="light">
          No pude detectar la IP pública (ifconfig.me / ipify no respondieron).
          Mírala en tu panel de cloud provider o ejecuta{' '}
          <Code>curl ifconfig.me</Code> en el servidor.
        </Alert>
      )}
    </Stack>
  );
}

function Step2DnsRecords({ status }: { status: HostingStatus | undefined }) {
  const ip = status?.public_ip;
  return (
    <Stack gap="xs">
      <Text fw={500}>
        <Badge mr="xs" size="sm">
          2
        </Badge>
        Añade estos registros DNS en Cloudflare
      </Text>
      <Text size="sm" c="dimmed">
        En tu zona DNS, crea dos registros A con el <strong>proxy ON</strong>
        {' '}(nube naranja). El wildcard es el que permite los subdominios de
        cada proyecto.
      </Text>
      <Card withBorder radius="sm" p="xs">
        <Stack gap={4}>
          <Group gap="xs">
            <Badge size="sm" color="gray">
              A
            </Badge>
            <Code>@</Code>
            <Text size="xs" c="dimmed">
              →
            </Text>
            <Code>{ip || '<tu IP>'}</Code>
            <Badge size="xs" color="orange" variant="light">
              proxy
            </Badge>
          </Group>
          <Group gap="xs">
            <Badge size="sm" color="gray">
              A
            </Badge>
            <Code>*</Code>
            <Text size="xs" c="dimmed">
              →
            </Text>
            <Code>{ip || '<tu IP>'}</Code>
            <Badge size="xs" color="orange" variant="light">
              proxy
            </Badge>
          </Group>
        </Stack>
      </Card>
      <Text size="xs" c="dimmed">
        En Cloudflare, el modo SSL/TLS debe ser <strong>Flexible</strong> o
        {' '}<strong>Full</strong> (no &quot;Full (strict)&quot; — el servidor
        no tiene cert). La opción más simple es Flexible.
      </Text>
    </Stack>
  );
}

function Step3Domain({
  domainInput,
  setDomainInput,
  onSave,
  saving,
  status,
}: {
  domainInput: string;
  setDomainInput: (s: string) => void;
  onSave: () => void;
  saving: boolean;
  status: HostingStatus | undefined;
}) {
  const currentDomain = status?.domain || '';
  const changed = domainInput.trim().toLowerCase() !== currentDomain;
  return (
    <Stack gap="xs">
      <Text fw={500}>
        <Badge mr="xs" size="sm">
          3
        </Badge>
        Escribe aquí tu dominio
      </Text>
      <Group gap="xs">
        <TextInput
          placeholder="midominio.com"
          value={domainInput}
          onChange={(e) => setDomainInput(e.currentTarget.value)}
          style={{ flex: 1 }}
        />
        <Button
          onClick={onSave}
          loading={saving}
          disabled={!changed || !domainInput.trim()}
        >
          Guardar
        </Button>
      </Group>
      {currentDomain && (
        <Text size="xs" c="dimmed">
          Actualmente guardado: <Code>{currentDomain}</Code>
        </Text>
      )}
    </Stack>
  );
}

function Step4Verify({
  status,
  isLoading,
}: {
  status: HostingStatus | undefined;
  isLoading: boolean;
}) {
  if (!status) {
    return null;
  }
  const hasDomain = Boolean(status.domain);
  const dnsOk = status.dns.ips.length > 0;
  const wildcardOk = status.wildcard.ips.length > 0;
  const httpOk = status.http.ok;
  const caddyOk = status.caddy_listening;
  const allOk = hasDomain && dnsOk && wildcardOk && httpOk && caddyOk;

  return (
    <Stack gap="xs">
      <Text fw={500}>
        <Badge mr="xs" size="sm">
          4
        </Badge>
        Estado de la configuración
      </Text>
      {isLoading ? (
        <Loader size="sm" />
      ) : !hasDomain ? (
        <Alert color="gray" variant="light">
          Guarda un dominio en el paso 3 para poder verificar.
        </Alert>
      ) : (
        <Stack gap="xs">
          <StatusLine
            ok={dnsOk}
            label={
              <>
                <Code>{status.domain}</Code>{' '}
                {dnsOk
                  ? `→ ${status.dns.ips.join(', ')}`
                  : 'no resuelve (DNS aún no propagado)'}
              </>
            }
          />
          <StatusLine
            ok={wildcardOk}
            label={
              <>
                <Code>{status.wildcard.host}</Code>{' '}
                {wildcardOk
                  ? `→ ${status.wildcard.ips.join(', ')} (wildcard OK)`
                  : 'no resuelve (falta registro * o no propagado)'}
              </>
            }
          />
          <StatusLine
            ok={httpOk}
            label={
              httpOk
                ? `HTTP OK vía ${status.http.url} (${status.http.status})`
                : 'El dominio no responde a HTTP/HTTPS todavía'
            }
          />
          <StatusLine
            ok={caddyOk}
            label={
              caddyOk
                ? `Caddy hosting escuchando en :${status.port}`
                : `Caddy no escucha en :${status.port} (hace falta al menos un deploy)`
            }
          />
          {allOk && (
            <Alert color="green" variant="light" mt="xs">
              ¡Listo! Los deploys futuros usarán
              {' '}<Code>{`https://<slug>.${status.domain}/`}</Code>.
            </Alert>
          )}
        </Stack>
      )}
    </Stack>
  );
}
