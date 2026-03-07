import type { ChatMessage } from '../types/api';

type MessageBubbleProps = {
  message: ChatMessage;
};

export function MessageBubble({ message }: MessageBubbleProps) {
  const role = message.role === 'assistant' ? 'assistant' : 'user';

  return (
    <article className={`message-bubble message-bubble--${role}`}>
      <header>
        <span>{role === 'assistant' ? 'Assistant' : 'You'}</span>
        <time>{new Date(message.created_at).toLocaleTimeString()}</time>
      </header>
      <p>{message.content}</p>
    </article>
  );
}
