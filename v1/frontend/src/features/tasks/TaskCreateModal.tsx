import { Button, Group, Modal, Stack, TextInput, Textarea } from "@mantine/core";
import { useForm } from "@mantine/form";
import { notifications } from "@mantine/notifications";

import { ApiError, type TaskCreatePayload } from "../../api";
import { useCreateTask } from "./api";

interface Props {
  slug: string;
  opened: boolean;
  onClose: () => void;
}

interface FormValues {
  title: string;
  description: string;
}

const INITIAL: FormValues = { title: "", description: "" };

// Backend `TaskCreate` allows title 1-200 chars and description up to
// 10 000 chars; we mirror the title bounds here and leave description
// validation to the backend (soft limit via Textarea `autosize`).
const TITLE_MAX = 200;

export function TaskCreateModal({ slug, opened, onClose }: Props) {
  const mutation = useCreateTask(slug);

  const form = useForm<FormValues>({
    mode: "controlled",
    initialValues: INITIAL,
    validateInputOnChange: true,
    validate: {
      title: (value) => {
        const trimmed = value.trim();
        if (trimmed.length === 0) return "title required";
        if (trimmed.length > TITLE_MAX) return `max ${TITLE_MAX} chars`;
        return null;
      },
    },
  });

  // Gate the submit button on a valid, non-empty title so the user can't
  // fire a 422. `form.isValid()` re-evaluates against the current values.
  const canSubmit = form.isValid("title");

  const handleSubmit = form.onSubmit((values) => {
    const payload: TaskCreatePayload = {
      title: values.title.trim(),
      description: values.description.trim() || null,
    };
    mutation.mutate(payload, {
      onSuccess: (task) => {
        notifications.show({
          title: "Tarea creada",
          message: task.title,
          color: "green",
        });
        form.reset();
        onClose();
      },
      onError: (err) => {
        const detail =
          err instanceof ApiError && err.status === 404
            ? "El proyecto ya no existe"
            : err.message;
        notifications.show({
          title: "No se pudo crear la tarea",
          message: detail,
          color: "red",
        });
      },
    });
  });

  return (
    <Modal opened={opened} onClose={onClose} title="Nueva tarea" centered>
      <form onSubmit={handleSubmit}>
        <Stack gap="sm">
          <TextInput
            label="Title"
            placeholder="Add dark mode toggle"
            required
            {...form.getInputProps("title")}
          />
          <Textarea
            label="Description"
            placeholder="Optional details, constraints, acceptance criteria…"
            autosize
            minRows={3}
            maxRows={8}
            {...form.getInputProps("description")}
          />
          <Group justify="flex-end" mt="md">
            <Button variant="default" onClick={onClose} type="button">
              Cancelar
            </Button>
            <Button
              type="submit"
              loading={mutation.isPending}
              disabled={!canSubmit}
            >
              Crear
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
