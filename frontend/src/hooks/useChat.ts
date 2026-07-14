import { useRef, useState } from "react";

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------
// Backend base URL. If you change the backend port, update this and the CORS
// allow_origins list in backend/main.py.
const API_BASE = "http://localhost:8000";

// ---------------------------------------------------------------------------
// Types (exported so the UI component can use them)
// ---------------------------------------------------------------------------
export type Pill = { node: string; status: string };

export type Message = {
  role: "user" | "assistant";
  content: string;
  pdfName?: string;
  // Pills are keyed by node name and updated in place — never appended
  // blindly — so each node shows exactly ONE pill whose status changes
  // (running -> done / error). This is what kills the old duplication.
  pills?: Pill[];
  status?: "running" | "done" | "failed" | "partial";
  isError?: boolean;
};

type AttachedDoc = { docId: string; name: string };
type ErrorData = { message?: string; status?: number; title?: string; node?: string };

// ---------------------------------------------------------------------------
// Error copy — the single place messages live. The backend already sends a
// user-safe `message`; this map is the fallback keyed by HTTP status.
// ---------------------------------------------------------------------------
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

function resolveErrorMessage(data?: ErrorData): string {
  if (data?.message) return data.message;
  if (data?.status && ERROR_MESSAGES[String(data.status)]) return ERROR_MESSAGES[String(data.status)];
  if (data?.title) return data.title;
  return ERROR_MESSAGES.unknown;
}

// Builds the "Issue with the analysis node — <reason>" headline.
function buildErrorText(data?: ErrorData): string {
  const reason = resolveErrorMessage(data);
  const node = data?.node;
  if (node && NODE_LABELS[node]) return `Issue with the ${NODE_LABELS[node]} node — ${reason}`;
  return reason;
}

// Upsert a pill by node name: update the existing pill's status if the node
// already has one, else add it. One pill per node, status changes in place.
function upsertPill(pills: Pill[] | undefined, node: string, status: string): Pill[] {
  const list = pills ? [...pills] : [];
  const idx = list.findIndex((p) => p.node === node);
  if (idx >= 0) list[idx] = { node, status };
  else list.push({ node, status });
  return list;
}

// ---------------------------------------------------------------------------
// useChat — owns all chat state + the SSE streaming logic. The UI is dumb;
// this hook is the single owner of behavior. Logic is unchanged from the
// original App.tsx, only relocated.
// ---------------------------------------------------------------------------
export function useChat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [attachedDoc, setAttachedDoc] = useState<AttachedDoc | null>(null);
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

  // Write a clean assistant-style error into the CURRENT bubble in place —
  // no blank bubble, no second bubble. Pills stay visible above it.
  function setErrorOnLastMessage(text: string, failedNode?: string) {
    setMessages((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      if (last && last.role === "assistant") {
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

  return {
    messages,
    input,
    setInput,
    pendingFile,
    attachedDoc,
    streaming,
    fileInputRef,
    handleFileSelect,
    clearAttachment,
    handleSend,
  };
}
