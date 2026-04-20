import { Button, Group, Modal, Select, Stack, TextInput } from "@mantine/core";
import { useForm, isNotEmpty, hasLength } from "@mantine/form";
import { notifications } from "@mantine/notifications";

import { ApiError, type ProjectCreatePayload, type ProjectKind, type AutonomyMode } from "../../api";
import { useCreateProject } from "./api";

interface Props {
  opened: boolean;
  onClose: () => void;
}

interface FormValues {
  slug: string;
  name: string;
  kind: ProjectKind;
  local_path: string;
  git_remote: string;
  autonomy_mode: AutonomyMode;
  deploy_port: string;
}

const INITIAL: FormValues = {
  slug: "",
  name: "",
  kind: "library",
  local_path: "",
  git_remote: "",
  autonomy_mode: "safe",
  deploy_port: "",
};

export function ProjectCreateModal({ opened, onClose }: Props) {
  const mutation = useCreateProject();

  const form = useForm<FormValues>({
    initialValues: INITIAL,
    validate: {
      slug: (v) =>
        /^[a-z0-9-]{3,40}$/.test(v) ? null : "slug: a-z, 0-9, '-' (3-40 chars)",
      name: hasLength({ min: 1, max: 200 }, "name: 1-200 chars"),
      local_path: isNotEmpty("local_path required"),
      kind: isNotEmpty("kind required"),
    },
  });

  const handleSubmit = form.onSubmit((values) => {
    const payload: ProjectCreatePayload = {
      slug: values.slug,
      name: values.name,
      kind: values.kind,
      local_path: values.local_path,
      autonomy_mode: values.autonomy_mode,
      git_remote: values.git_remote.trim() || null,
      deploy_port: values.deploy_port.trim() ? Number(values.deploy_port) : null,
    };

    mutation.mutate(payload, {
      onSuccess: (project) => {
        notifications.show({
          title: "Proyecto creado",
          message: project.name,
          color: "green",
        });
        form.reset();
        onClose();
      },
      onError: (err) => {
        const detail =
          err instanceof ApiError && err.status === 409
            ? "El slug ya existe"
            : err.message;
        notifications.show({
          title: "No se pudo crear el proyecto",
          message: detail,
          color: "red",
        });
      },
    });
  });

  return (
    <Modal opened={opened} onClose={onClose} title="Nuevo proyecto" centered>
      <form onSubmit={handleSubmit}>
        <Stack gap="sm">
          <TextInput
            label="Slug"
            placeholder="my-project"
            required
            {...form.getInputProps("slug")}
          />
          <TextInput
            label="Name"
            placeholder="My Project"
            required
            {...form.getInputProps("name")}
          />
          <Select
            label="Kind"
            required
            data={[
              { value: "web-deployable", label: "web-deployable" },
              { value: "library", label: "library" },
              { value: "script", label: "script" },
            ]}
            {...form.getInputProps("kind")}
          />
          <TextInput
            label="Local path"
            placeholder="/home/user/code/my-project"
            required
            {...form.getInputProps("local_path")}
          />
          <TextInput
            label="Git remote (optional)"
            placeholder="git@github.com:user/repo.git"
            {...form.getInputProps("git_remote")}
          />
          <Select
            label="Autonomy mode"
            data={[
              { value: "safe", label: "safe" },
              { value: "dangerous", label: "dangerous" },
            ]}
            {...form.getInputProps("autonomy_mode")}
          />
          <TextInput
            label="Deploy port (optional)"
            placeholder="3000"
            {...form.getInputProps("deploy_port")}
          />
          <Group justify="flex-end" mt="md">
            <Button variant="default" onClick={onClose} type="button">
              Cancelar
            </Button>
            <Button type="submit" loading={mutation.isPending}>
              Crear
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
