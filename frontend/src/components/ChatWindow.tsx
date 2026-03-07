import type { ChatMessage } from '../types/api';
import { MessageBubble } from './MessageBubble';

type ChatWindowProps = {
  messages: ChatMessage[];
  loading?: boolean;
};

export function ChatWindow({ messages, loading = false }: ChatWindowProps) {
  return (
    <section className="chat-window card">
      <div className="chat-window__messages">
        {messages.length === 0 ? <p className="empty-state">No messages yet. Start with a question.</p> : null}
        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}
        {loading ? <p className="status-inline">Generating grounded answer…</p> : null}
      </div>
    </section>
  );
}
