import { useState } from 'react';
import {
  Stack,
  Text,
  Loader,
  Center,
  Group,
  UnstyledButton,
  Box,
  Collapse,
} from '@mantine/core';
import { IconFolder, IconFolderOpen, IconFile } from '@tabler/icons-react';
import { useProjectTree, useProjectFolderFiles } from '../hooks/useProjects';

interface Props {
  slug: string;
}

function FolderNode({
  name,
  slug,
  path,
}: {
  name: string;
  slug: string;
  path: string;
}) {
  const [opened, setOpened] = useState(false);
  const { data, isLoading } = useProjectFolderFiles(slug, opened ? path : null);

  return (
    <Box>
      <UnstyledButton
        onClick={() => setOpened((o) => !o)}
        py={2}
        px={4}
        style={{
          borderRadius: 4,
          width: '100%',
          '&:hover': { backgroundColor: 'var(--mantine-color-dark-5)' },
        }}
      >
        <Group gap={6}>
          {opened ? (
            <IconFolderOpen size={16} color="var(--mantine-color-brand-5)" />
          ) : (
            <IconFolder size={16} color="var(--mantine-color-brand-5)" />
          )}
          <Text size="sm">{name}</Text>
        </Group>
      </UnstyledButton>
      <Collapse in={opened}>
        <Box pl="md">
          {isLoading ? (
            <Loader size="xs" />
          ) : (
            <Stack gap={0}>
              {data?.files?.map((f) =>
                f.type === 'folder' ? (
                  <FolderNode
                    key={f.name}
                    name={f.name}
                    slug={slug}
                    path={`${path}/${f.name}`}
                  />
                ) : (
                  <Group key={f.name} gap={6} py={2} px={4}>
                    <IconFile size={14} color="var(--mantine-color-dimmed)" />
                    <Text size="xs" c="dimmed">
                      {f.name}
                    </Text>
                    {f.size !== undefined && (
                      <Text size="xs" c="dimmed">
                        ({formatSize(f.size)})
                      </Text>
                    )}
                  </Group>
                ),
              )}
            </Stack>
          )}
        </Box>
      </Collapse>
    </Box>
  );
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function FileTree({ slug }: Props) {
  const { data, isLoading } = useProjectTree(slug, 'folders');

  if (isLoading) {
    return (
      <Center py="md">
        <Loader size="sm" />
      </Center>
    );
  }

  if (!data?.tree?.length) {
    return (
      <Text c="dimmed" size="sm" ta="center" py="md">
        Sin archivos
      </Text>
    );
  }

  return (
    <Stack gap={0}>
      {data.tree.map((node) =>
        node.type === 'folder' ? (
          <FolderNode key={node.name} name={node.name} slug={slug} path={node.name} />
        ) : (
          <Group key={node.name} gap={6} py={2} px={4}>
            <IconFile size={14} color="var(--mantine-color-dimmed)" />
            <Text size="xs" c="dimmed">
              {node.name}
            </Text>
          </Group>
        ),
      )}
      {data.root_file_count > 0 && (
        <Text size="xs" c="dimmed" mt="xs">
          + {data.root_file_count} archivos en la raíz
        </Text>
      )}
    </Stack>
  );
}
