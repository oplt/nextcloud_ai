import { useEffect, useRef } from 'react';
import type { ChatMessage } from '../types/api';
import { MessageBubble } from './MessageBubble';

type ChatWindowProps = {
  messages: ChatMessage[];
  loading?: boolean;
  activeAssistantMessageId?: string | null;
  onSelectAssistantMessage?: (messageId: string) => void;
};

function TypingIndicator() {
  return (
    <article className="message-bubble message-bubble--assistant message-bubble--typing" aria-live="polite" aria-label="Assistant is typing">
      <header>
        <span>Assistant</span>
      </header>
      <p>
        <span className="typing-dots">
          <span />
          <span />
          <span />
        </span>
      </p>
    </article>
  );
}

export function ChatWindow({
  messages,
  loading = false,
  activeAssistantMessageId = null,
  onSelectAssistantMessage,
}: ChatWindowProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length, loading]);

  return (
    <section className="chat-window card" aria-live="polite" aria-label="Chat messages">
      <div className="chat-window__messages">
        {messages.length === 0 && !loading ? (
          <div className="empty-state">
            <div className="empty-state-icon" aria-hidden="true">
              <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M17 13a2 2 0 0 1-2 2H6l-3 3V5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v8z" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <span>No messages yet — ask a question below.</span>
          </div>
        ) : null}

        {messages.map((message) => (
          <MessageBubble
            key={message.id}
            message={message}
            selected={message.role === 'assistant' && message.id === activeAssistantMessageId}
            onSelect={onSelectAssistantMessage}
          />
        ))}

        {loading ? <TypingIndicator /> : null}
        <div ref={bottomRef} aria-hidden="true" />
      </div>
    </section>
  );
}
