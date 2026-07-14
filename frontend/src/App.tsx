import { useChat } from "./hooks/useChat";
import { ChatUI } from "./components/ChatUI";

// Thin shell: layout + header. All chat state/logic lives in useChat; all
// presentation lives in ChatUI.
export default function App() {
  const chat = useChat();

  return (
    <div className="flex flex-col h-screen max-w-2xl mx-auto">
      <header className="px-4 py-3 border-b border-neutral-800 text-sm text-neutral-400">
        Research Assistant
      </header>
      <ChatUI chat={chat} />
    </div>
  );
}
