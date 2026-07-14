import { useRef, useState } from "react";

const API_BASE = "http://localhost:8000";

type TraceEvent = { step: number; node: string; status: string; detail: string };

type Message = {
  role: "user" | "assistant";
  content: string;
  pdfName?: string;
  // Pills are keyed by node name and updated in place — never appended
  // blindly — so each node shows exactly ONE pill whose status changes
  // (running -> done / error). This is what kills the old duplication.
  pills?: { node: string; status: string }[];
  status?: "running" | "done" | "failed" | "partial";
  isError?: boolean;
};

// Centralized error copy — the single place messages live. Backend already
// sends a user-safe `message`; this map is the fallback keyed by status.
const ERROR_MESSAGES: Record<string, string> = {
  "401": "Authentication failed. Please verify your API key.",
  "403": "Permission denied.",
  "404": "Requested model not found.",
  "408": "Request timed out. Please try again.",
  "429": "Rate limit exceeded. Please wait a moment before trying again.",
  "500": "Internal server error. Please try again.",
  "502": "Gateway error. Please try again.",
  "503": "The model is temporarily unavailable. Please try again in a minute.",
  network: "Cannot reach the backend.",
  unknown: "Something unexpected happened.",
};

// Friendly node labels for the error headline ("Issue with the analysis node").
const NODE_LABELS: Record<string, string> = {
  planner: "planner",
  gatherer_pdf: "PDF search",
  gatherer_web: "web search",
  gatherer_both: "source gathering",
  analyser: "analysis",
  writer: "writer",
  ingest_pdf: "PDF ingestion",
  database: "database",
};

function resolveErrorMessage(data?: { message?: string; status?: number; title?: string }): string {
  if (data?.message) return data.message;
  if (data?.status && ERROR_MESSAGES[String(data.status)]) return ERROR_MESSAGES[String(data.status)];
  if (data?.title) return data.title;
  return ERROR_MESSAGES.unknown;
}

// Builds the "Issue with the analysis node — <reason>" headline.
function buildErrorText(data?: { message?: string; status?: number; title?: string; node?: string }): string {
  const reason = resolveErrorMessage(data);
  const node = data?.node;
  if (node && NODE_LABELS[node]) {
    return `Issue with the ${NODE_LABELS[node]} node — ${reason}`;
  }
  return reason;
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [attachedDoc, setAttachedDoc] = useState<{ docId: string; name: string } | null>(null);
  const [streaming, setStreaming] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.type !== "application/pdf") {
      alert("Only PDF files are supported.");
      return;
    }
    setPendingFile(file);
    setAttachedDoc(null);
    e.target.value = "";
  }

  function clearAttachment() {
    setPendingFile(null);
    setAttachedDoc(null);
  }

  // Upsert a pill by node name: update the existing pill's status if the node
  // already has one, else add it. One pill per node, status changes in place.
  function upsertPill(pills: { node: string; status: string }[] | undefined, node: string, status: string) {
    const list = pills ? [...pills] : [];
    const idx = list.findIndex((p) => p.node === node);
    if (idx >= 0) list[idx] = { node, status };
    else list.push({ node, status });
    return list;
  }

  // Write a clean assistant-style error into the CURRENT bubble in place —
  // no blank bubble, no second bubble. Pills stay visible above it.
  function setErrorOnLastMessage(text: string, failedNode?: string) {
    setMessages((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      if (last && last.role === "assistant") {
        // Make sure the failing node's pill reads as an error.
        if (failedNode) last.pills = upsertPill(last.pills, failedNode, "error");
        last.content = `⚠️ ${text}`;
        last.status = "failed";
        last.isError = true;
      }
      return next;
    });
  }

  async function handleSend() {
    if (!input.trim() || streaming) return;
    const goal = input.trim();
    const attachmentLabel = pendingFile?.name ?? attachedDoc?.name;

    setMessages((m) => [...m, { role: "user", content: goal, pdfName: attachmentLabel }]);
    // Assistant placeholder — "Working…" shows immediately and stays pinned
    // above the pills for the whole run (content stays empty until the end).
    setMessages((m) => [...m, { role: "assistant", content: "", pills: [], status: "running" }]);
    setInput("");
    setStreaming(true);

    let settled = false; // did a terminal event (complete/error) arrive?

    try {
      const form = new FormData();
      form.append("goal", goal);
      if (pendingFile) form.append("file", pendingFile);
      else if (attachedDoc) form.append("doc_id", attachedDoc.docId);

      const res = await fetch(`${API_BASE}/chat`, { method: "POST", body: form });

      if (!res.ok || !res.body) {
        settled = true;
        setErrorOnLastMessage(resolveErrorMessage({ status: res.status }) || ERROR_MESSAGES.network);
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() ?? "";

        for (const block of blocks) {
          const eventLine = block.split("\n").find((l) => l.startsWith("event:"));
          const dataLine = block.split("\n").find((l) => l.startsWith("data:"));
          if (!eventLine || !dataLine) continue;
          const event = eventLine.replace("event:", "").trim();

          let data: any;
          try {
            data = JSON.parse(dataLine.replace("data:", "").trim());
          } catch {
            continue; // skip malformed frame instead of crashing the loop
          }

          if (event === "error") {
            settled = true;
            setErrorOnLastMessage(buildErrorText(data), data?.node);
            continue;
          }

          if (event === "doc_ingested") {
            setAttachedDoc({ docId: data.doc_id, name: data.filename });
          }

          setMessages((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (!last || last.role !== "assistant") return next;
            if (last.isError) return next; // don't overwrite a shown error

            if (event === "node_update" && data.trace_tail) {
              // Upsert one pill per node using the trace entry's status
              // (running / done / failed). failed -> shown as "error".
              const st = data.trace_tail.status === "failed" ? "error" : data.trace_tail.status;
              last.pills = upsertPill(last.pills, data.trace_tail.node, st);
            }

            if (event === "task_complete") {
              settled = true;
              if (data.final_result) {
                last.content = data.final_result;
                last.status = data.status;
              } else {
                // Shouldn't happen on the success path, but never render a raw
                // error string as an answer — show a clean fallback.
                last.content = `⚠️ ${resolveErrorMessage({ message: data.error })}`;
                last.status = "failed";
                last.isError = true;
              }
            }
            return next;
          });
        }
      }

      if (!settled) setErrorOnLastMessage(ERROR_MESSAGES.unknown);
    } catch {
      if (!settled) setErrorOnLastMessage(ERROR_MESSAGES.network);
    } finally {
      setStreaming(false);
      setPendingFile(null);
    }
  }

  return (
    <div className="flex flex-col h-screen max-w-2xl mx-auto">
      <header className="px-4 py-3 border-b border-neutral-800 text-sm text-neutral-400">
        Research Assistant
      </header>

      <main className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
            <div
              className={
                m.role === "user"
                  ? "bg-neutral-100 text-neutral-900 rounded-2xl rounded-br-sm px-4 py-2 max-w-md"
                  : "bg-neutral-900 rounded-2xl rounded-bl-sm px-4 py-3 max-w-md space-y-2"
              }
            >
              {m.role === "user" && m.pdfName && (
                <div className="text-xs text-neutral-500 mb-1">📎 {m.pdfName}</div>
              )}

              {/* "Working…" pinned above the pills for the whole run */}
              {m.role === "assistant" && m.status === "running" && !m.content && (
                <div className="text-sm text-neutral-500">Working…</div>
              )}

              {/* One pill per node; status updates in place */}
              {m.role === "assistant" && m.pills && m.pills.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {m.pills.map((p, j) => (
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
              )}

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
        ))}
      </main>

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
    </div>
  );
}
