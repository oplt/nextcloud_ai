import { useCallback, useState } from 'react';
import type { FormEvent, KeyboardEvent } from 'react';
import SendIcon from '@mui/icons-material/Send';
import IconButton from '@mui/material/IconButton';

import { AppTextField } from './ui/AppTextField';

type ChatInputProps = {
  onSubmit: (question: string) => Promise<void>;
  disabled?: boolean;
};



export function ChatInput({ onSubmit, disabled = false }: ChatInputProps) {
  const [question, setQuestion] = useState('');

  const handleSubmit = useCallback(
    async (e?: FormEvent<HTMLFormElement>) => {
      e?.preventDefault();
      const trimmed = question.trim();
      if (!trimmed || disabled) return;
      try {
        await onSubmit(trimmed);
        setQuestion('');
      } catch {
        // keep draft on error
      }
    },
    [question, disabled, onSubmit],
  );

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLDivElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        void handleSubmit();
      }
    },
    [handleSubmit],
  );

  const canSend = !disabled && question.trim().length > 0;

  return (
    <form className="chat-input" onSubmit={handleSubmit} aria-label="Chat message form">
      <AppTextField
        multiline
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Ask a question about your company knowledge..."
        rows={2}
        disabled={disabled}
        aria-label="Message input"
        InputProps={{
          sx: {
            alignItems: 'stretch',
            textarea: {
              minHeight: '2rem !important',
            },
          },
        }}
      />
      <IconButton
        type="submit"
        className="chat-input-send"
        disabled={!canSend}
        aria-label="Send message"
        title="Send"
        color="primary"
      >
        <SendIcon />
      </IconButton>
    </form>
  );
}
