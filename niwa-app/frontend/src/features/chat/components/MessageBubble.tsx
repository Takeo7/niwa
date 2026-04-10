import { Box, Paper, Text, Loader } from '@mantine/core';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { ChatMessage } from '../../../shared/types';

interface Props {
  message: ChatMessage;
}

function extractImages(content: string): { text: string; images: string[] } {
  const images: string[] = [];
  const imagePattern = /(https?:\/\/\S+\.(?:png|jpg|jpeg|gif|webp))/gi;
  const generatedPattern = /\/static\/generated-images\/[^\s)]+/g;

  let text = content;
  const urlMatches = content.match(imagePattern) || [];
  const genMatches = content.match(generatedPattern) || [];
  images.push(...urlMatches, ...genMatches);

  for (const img of images) {
    text = text.replace(img, '');
  }

  return { text: text.trim(), images: [...new Set(images)] };
}

export function MessageBubble({ message }: Props) {
  const isUser = message.role === 'user';
  const isPending = message.status === 'pending' && !message.content;
  const { text, images } = extractImages(message.content || '');

  return (
    <Box
      style={{
        display: 'flex',
        justifyContent: isUser ? 'flex-end' : 'flex-start',
        marginBottom: 8,
      }}
    >
      <Paper
        p="sm"
        radius="lg"
        maw="75%"
        style={{
          backgroundColor: isUser
            ? 'var(--mantine-color-brand-7)'
            : 'var(--mantine-color-dark-6)',
        }}
      >
        {isPending ? (
          <Loader size="sm" type="dots" />
        ) : (
          <>
            {text && (
              <Box
                fz="sm"
                style={{
                  '& p': { margin: 0 },
                  '& pre': {
                    backgroundColor: 'var(--mantine-color-dark-8)',
                    padding: 8,
                    borderRadius: 8,
                    overflow: 'auto',
                  },
                  '& code': {
                    fontSize: '0.85em',
                  },
                }}
              >
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {text}
                </ReactMarkdown>
              </Box>
            )}
            {images.map((src) => (
              <Box key={src} mt="xs">
                <img
                  src={src}
                  alt="Imagen generada"
                  style={{
                    maxWidth: '100%',
                    borderRadius: 8,
                  }}
                />
              </Box>
            ))}
            <Text size="xs" c="dimmed" mt={4} ta={isUser ? 'right' : 'left'}>
              {new Date(message.created_at).toLocaleTimeString('es-ES', {
                hour: '2-digit',
                minute: '2-digit',
              })}
            </Text>
          </>
        )}
      </Paper>
    </Box>
  );
}
