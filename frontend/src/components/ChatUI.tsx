import type { useChat } from "../hooks/useChat";
import type { Message, Pill } from "../hooks/useChat";

type ChatController = ReturnType<typeof useChat>;

function TracePills({ pills }: { pills: Pill[] }) {
  if (!pills.length) return null;
  return (
    <div className="flex flex-wrap gap-1">
      {pills.map((p, j) => (
        <span
          key={j}
          className={
            "text-xs px-2 py-0.5 rounded-full " +
            (p.status === "error"
              ? "bg-red-950 text-red-400"
              : p.status === "running"
              ? "bg-neutral-800 text-neutral-300"
              : "bg-neutral-800 text-neutral-500")
          }
        >
          {p.node} · {p.status}
        </span>
      ))}
    </div>
  );
}

function ChatMessage({ m }: { m: Message }) {
  const isUser = m.role === "user";
  return (
    <div className={isUser ? "flex justify-end" : "flex justify-start"}>
      <div
        className={
          isUser
            ? "bg-neutral-100 text-neutral-900 rounded-2xl rounded-br-sm px-4 py-2 max-w-md"
            : "bg-neutral-900 rounded-2xl rounded-bl-sm px-4 py-3 max-w-md space-y-2"
        }
      >
        {isUser && m.pdfName && <div className="text-xs text-neutral-500 mb-1">📎 {m.pdfName}</div>}

  
        {!isUser && m.status === "running" && !m.content && (
          <div className="text-sm text-neutral-500">Working…</div>
        )}

             {!isUser && m.pills && <TracePills pills={m.pills} />}

        {m.content && (
          <div
            className={
              m.isError ? "text-sm whitespace-pre-wrap text-amber-400" : "text-sm whitespace-pre-wrap"
            }
          >
            {m.content}
          </div>
        )}
      </div>
    </div>
  );
}

function ChatComposer({ chat }: { chat: ChatController }) {
  const { input, setInput, pendingFile, attachedDoc, streaming, fileInputRef, handleFileSelect, clearAttachment, handleSend } = chat;
  return (
    <footer className="px-4 py-3 border-t border-neutral-800">
      {(pendingFile || attachedDoc) && (
        <div className="flex items-center gap-2 text-xs text-neutral-400 mb-2">
          📎 {pendingFile?.name ?? attachedDoc?.name}
          <button onClick={clearAttachment} className="text-neutral-500 hover:text-neutral-200">
            ✕
          </button>
        </div>
      )}
      <div className="flex items-center gap-2 bg-neutral-900 rounded-full px-2 py-1">
        <button
          onClick={() => fileInputRef.current?.click()}
          className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-neutral-800 text-lg text-neutral-400"
          title="Attach a PDF"
        >
          +
        </button>
        <input ref={fileInputRef} type="file" accept="application/pdf" hidden onChange={handleFileSelect} />
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSend()}
          placeholder="Ask something…"
          className="flex-1 bg-transparent outline-none text-sm py-2"
        />
        <button
          onClick={handleSend}
          disabled={streaming || !input.trim()}
          className="w-8 h-8 flex items-center justify-center rounded-full bg-neutral-100 text-neutral-900 disabled:opacity-30 text-sm"
        >
          ↑
        </button>
      </div>
    </footer>
  );
}

// --- the whole chat surface: message list + composer ---
export function ChatUI({ chat }: { chat: ChatController }) {
  return (
    <>
      <main className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {chat.messages.map((m, i) => (
          <ChatMessage key={i} m={m} />
        ))}
      </main>
      <ChatComposer chat={chat} />
    </>
  );
}
