import { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Group,
  Modal,
  NumberInput,
  Stack,
  Switch,
  Text,
  TextInput,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconAlertTriangle } from '@tabler/icons-react';
import { useUpdateBackendProfile } from '../../../shared/api/queries';
import { ApiError } from '../../../shared/api/client';
import type {
  BackendProfile,
  BackendProfilePatch,
} from '../../../shared/types';

interface Props {
  profile: BackendProfile;
  opened: boolean;
  onClose: () => void;
}

/** Modal de edición — sólo los tres campos que el SPEC PR-10d
 *  permite tocar: ``enabled``, ``priority``, ``default_model``.
 *
 *  Nota sobre semántica del codex profile:
 *  tras la primera edición manual del row de codex
 *  (enabled o priority distinto de los defaults PR-03 que son
 *  ``enabled=0 priority=0``), el UPDATE condicional de
 *  ``upgrade_codex_profile()`` deja de dispararse (PR-07 Dec 4).
 *  Cambios explícitos desde la UI "congelan" la fila frente a
 *  futuros upgrades automáticos — comportamiento deseado.
 */
export function BackendProfileEditModal({ profile, opened, onClose }: Props) {
  const [enabled, setEnabled] = useState<boolean>(!!profile.enabled);
  const [priority, setPriority] = useState<number>(profile.priority);
  const [defaultModel, setDefaultModel] = useState<string>(
    profile.default_model ?? '',
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setEnabled(!!profile.enabled);
    setPriority(profile.priority);
    setDefaultModel(profile.default_model ?? '');
    setError(null);
  }, [profile.id, profile.enabled, profile.priority, profile.default_model]);

  const update = useUpdateBackendProfile();

  const handleSave = async () => {
    setError(null);
    const patch: BackendProfilePatch = {};
    if (enabled !== !!profile.enabled) patch.enabled = enabled;
    if (priority !== profile.priority) patch.priority = priority;
    const trimmed = defaultModel.trim();
    const currentModel = profile.default_model ?? '';
    if (trimmed !== currentModel) {
      patch.default_model = trimmed === '' ? null : trimmed;
    }

    if (Object.keys(patch).length === 0) {
      onClose();
      return;
    }

    try {
      await update.mutateAsync({ id: profile.id, ...patch });
      notifications.show({
        title: 'Backend actualizado',
        message: `${profile.display_name} guardado`,
        color: 'green',
      });
      onClose();
    } catch (e) {
      const msg =
        e instanceof ApiError
          ? e.message
          : 'No se pudo guardar el perfil';
      setError(msg);
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={`Editar ${profile.display_name}`}
      size="md"
    >
      <Stack gap="md">
        {profile.slug === 'codex' && (
          <Alert
            color="yellow"
            variant="light"
            icon={<IconAlertTriangle size={16} />}
          >
            <Text size="xs">
              Cambiar estos valores en <code>codex</code> desactiva el
              upgrade automático que aplica <code>seed_backend_profiles</code>{' '}
              al arrancar la app (PR-07). Tu ajuste se respeta entre
              arranques.
            </Text>
          </Alert>
        )}

        <Switch
          checked={enabled}
          onChange={(e) => setEnabled(e.currentTarget.checked)}
          label="Habilitado"
          description="Cuando está deshabilitado, el router no selecciona este backend."
        />

        <NumberInput
          label="Priority"
          description="El valor más alto gana en la resolución determinista de PR-06."
          value={priority}
          onChange={(v) => setPriority(typeof v === 'number' ? v : 0)}
          min={0}
          max={1000}
          allowDecimal={false}
          step={1}
        />

        <TextInput
          label="Default model"
          description="Modelo que el adapter usa si la tarea no pinea uno."
          value={defaultModel}
          onChange={(e) => setDefaultModel(e.currentTarget.value)}
          placeholder="claude-sonnet-4-6"
        />

        <Alert color="gray" variant="light">
          <Text size="xs" c="dimmed">
            Los runs ya en ejecución no se ven afectados — conservan el
            <code> capability_snapshot_json </code>
            de cuando arrancaron.
          </Text>
        </Alert>

        {error && (
          <Alert color="red" variant="light">
            <Text size="xs">{error}</Text>
          </Alert>
        )}

        <Group justify="flex-end" gap="xs">
          <Button variant="subtle" onClick={onClose} disabled={update.isPending}>
            Cancelar
          </Button>
          <Button onClick={handleSave} loading={update.isPending}>
            Guardar
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
