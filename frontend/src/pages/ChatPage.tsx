/**
 * ChatPage — thin wrapper around ChatWorkspace.
 *
 * This page previously duplicated all chat-state logic from OverviewPage.
 * It now delegates to ChatWorkspace, which centralises that logic and removes
 * the duplication of parseCitations / buildSourcesMapFromMessages.
 */
import { ChatWorkspace } from '../components/ChatWorkspace';
import type {
  ChatAskResponse,
  ChatSessionDetail,
  ChatSessionSummary,
} from '../types/api';

type ChatPageProps = {
  sessions: ChatSessionSummary[];
  activeSession: ChatSessionDetail | null;
  loading: boolean;
  onSelectSession: (sessionId: string) => Promise<void>;
  onAsk: (question: string) => Promise<ChatAskResponse>;
  onNewChat?: () => void;
  onDeleteSessions?: (sessionIds: string[]) => Promise<void>;
};

export function ChatPage({
  sessions,
  activeSession,
  loading,
  onSelectSession,
  onAsk,
  onNewChat,
  onDeleteSessions,
}: ChatPageProps) {
  return (
    <ChatWorkspace
      sessions={sessions}
      activeSession={activeSession}
      loading={loading}
      onSelectSession={onSelectSession}
      onAsk={onAsk}
      onNewChat={onNewChat}
      onDeleteSessions={onDeleteSessions}
    />
  );
}
