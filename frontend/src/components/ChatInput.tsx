import { useState } from 'react';
import type { FormEvent } from 'react';

type ChatInputProps = {
  onSubmit: (question: string) => Promise<void>;
  disabled?: boolean;
};

export function ChatInput({ onSubmit, disabled = false }: ChatInputProps) {
  const [question, setQuestion] = useState('');

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || disabled) {
      return;
    }
    setQuestion('');
    await onSubmit(trimmed);
  };

  return (
    <form className="chat-input" onSubmit={handleSubmit}>
      <textarea
        value={question}
        onChange={(event) => setQuestion(event.target.value)}
        placeholder="Ask a grounded question about company knowledge"
        rows={3}
        disabled={disabled}
      />
      <button type="submit" disabled={disabled || !question.trim()}>
        Send
      </button>
    </form>
  );
}
