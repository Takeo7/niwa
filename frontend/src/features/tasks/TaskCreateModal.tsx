import { useState } from "react";
import {
  ActionIcon,
  Button,
  Group,
  Modal,
  Stack,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";
import { Dropzone } from "@mantine/dropzone";
import { useForm } from "@mantine/form";
import { notifications } from "@mantine/notifications";
import { IconFile, IconUpload, IconX } from "@tabler/icons-react";

import { ApiError, type Task, type TaskCreatePayload } from "../../api";
import { uploadAttachment, useCreateTask } from "./api";

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

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function TaskCreateModal({ slug, opened, onClose }: Props) {
  const mutation = useCreateTask(slug);
  const [files, setFiles] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState(false);

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

  const removeFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const resetAndClose = () => {
    form.reset();
    setFiles([]);
    onClose();
  };

  const handleSubmit = form.onSubmit(async (values) => {
    const payload: TaskCreatePayload = {
      title: values.title.trim(),
      description: values.description.trim() || null,
    };
    setSubmitting(true);
    let task: Task;
    try {
      task = await mutation.mutateAsync(payload);
    } catch (err) {
      const detail =
        err instanceof ApiError && err.status === 404
          ? "El proyecto ya no existe"
          : err instanceof Error
            ? err.message
            : "Error desconocido";
      notifications.show({
        title: "No se pudo crear la tarea",
        message: detail,
        color: "red",
      });
      setSubmitting(false);
      return;
    }
    // Upload attachments sequentially. A failure on any one is reported
    // via toast but does not roll back the (already-created) task —
    // brief calls this "consistencia eventual".
    const failed: string[] = [];
    for (const file of files) {
      try {
        await uploadAttachment(task.id, file);
      } catch {
        failed.push(file.name);
      }
    }
    if (failed.length > 0) {
      notifications.show({
        title: "Algún adjunto falló",
        message: `No se subieron: ${failed.join(", ")}`,
        color: "red",
      });
    }
    notifications.show({
      title: "Tarea creada",
      message: task.title,
      color: "green",
    });
    setSubmitting(false);
    resetAndClose();
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
          <Dropzone
            onDrop={(accepted) => setFiles((prev) => [...prev, ...accepted])}
            multiple
          >
            <Group justify="center" gap="xs" mih={60} style={{ pointerEvents: "none" }}>
              <IconUpload size={20} />
              <Text size="sm" c="dimmed">
                Suelta archivos aquí o haz click
              </Text>
            </Group>
          </Dropzone>
          {files.length > 0 ? (
            <Stack gap={4}>
              {files.map((file, idx) => (
                <Group key={`${file.name}-${idx}`} gap="xs" wrap="nowrap">
                  <IconFile size={16} />
                  <Text size="sm" style={{ flex: 1 }} truncate>
                    {file.name}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {formatSize(file.size)}
                  </Text>
                  <ActionIcon
                    variant="subtle"
                    color="gray"
                    aria-label={`Quitar ${file.name}`}
                    onClick={() => removeFile(idx)}
                  >
                    <IconX size={14} />
                  </ActionIcon>
                </Group>
              ))}
            </Stack>
          ) : null}
          <Group justify="flex-end" mt="md">
            <Button variant="default" onClick={onClose} type="button">
              Cancelar
            </Button>
            <Button
              type="submit"
              loading={submitting || mutation.isPending}
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
