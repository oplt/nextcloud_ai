import type { ChatMessage } from '../types/api';

type MessageBubbleProps = {
  message: ChatMessage;
  selected?: boolean;
  onSelect?: (messageId: string) => void;
};

export function MessageBubble({ message, selected = false, onSelect }: MessageBubbleProps) {
  const isAssistant = message.role === 'assistant';
  const role        = isAssistant ? 'assistant' : 'user';

  const timeLabel = new Date(message.created_at).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
  });

  const handleClick = isAssistant && onSelect ? () => onSelect(message.id) : undefined;
  const handleKey   =
    isAssistant && onSelect
      ? (e: React.KeyboardEvent) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onSelect(message.id);
          }
        }
      : undefined;

  return (
    <article
      className={[
        'message-bubble',
        `message-bubble--${role}`,
        selected ? 'message-bubble--selected' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      onClick={handleClick}
      onKeyDown={handleKey}
      role={isAssistant ? 'button' : undefined}
      tabIndex={isAssistant ? 0 : undefined}
      aria-pressed={isAssistant ? selected : undefined}
    >
      <header>
        <span>{isAssistant ? 'Assistant' : 'You'}</span>
        <time dateTime={message.created_at}>{timeLabel}</time>
      </header>
      <p>{message.content}</p>
    </article>
  );
}
