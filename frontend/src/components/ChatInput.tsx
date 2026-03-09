import { useCallback, useState } from 'react';
import type { FormEvent, KeyboardEvent } from 'react';

type ChatInputProps = {
  onSubmit: (question: string) => Promise<void>;
  disabled?: boolean;
};

function SendIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path
        d="M17.5 2.5L9.5 10.5M17.5 2.5L12 17.5L9.5 10.5M17.5 2.5L2.5 8L9.5 10.5"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

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
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        void handleSubmit();
      }
    },
    [handleSubmit],
  );

  const canSend = !disabled && question.trim().length > 0;

  return (
    <form className="chat-input" onSubmit={handleSubmit} aria-label="Chat message form">
      <textarea
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Ask a question about your company knowledge… (⌘↵ to send)"
        rows={3}
        disabled={disabled}
        aria-label="Message input"
      />
      <button
        type="submit"
        className="chat-input-send"
        disabled={!canSend}
        aria-label="Send message"
        title="Send (⌘↵)"
      >
        <SendIcon />
      </button>
    </form>
  );
}
