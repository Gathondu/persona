import DOMPurify from "dompurify";
import { marked } from "marked";

export interface Message {
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
}

interface StreamPayload {
  token?: string;
  error?: string;
}

interface SendMessageArgs {
  input: string;
  isStreaming: boolean;
  sessionId: string;
  messages: Message[];
  setInput: (value: string) => void;
  setIsStreaming: (value: boolean) => void;
  threadEl: HTMLElement | null;
  onAssistantComplete?: () => void | Promise<void>;
}

interface SubmitMessageBindings {
  getInput: () => string;
  getIsStreaming: () => boolean;
  getMessages: () => Message[];
  getThreadEl: () => HTMLElement | null;
  setInput: (value: string) => void;
  setIsStreaming: (value: boolean) => void;
  sessionId: string;
  onAssistantComplete?: () => void | Promise<void>;
}

marked.setOptions({
  breaks: true,
  gfm: true,
});

export function renderMarkdown(content: string): string {
  const html = marked.parse(content, { async: false });
  return DOMPurify.sanitize(html);
}

export function scrollToBottom(threadEl: HTMLElement | null): void {
  if (threadEl) {
    threadEl.scrollTop = threadEl.scrollHeight;
  }
}

export async function sendMessage(args: SendMessageArgs): Promise<void> {
  const text = args.input.trim();
  if (!text || args.isStreaming) {
    return;
  }

  args.setInput("");
  args.setIsStreaming(true);

  args.messages.push({ role: "user", content: text });
  args.messages.push({ role: "assistant", content: "", streaming: true });
  scrollToBottom(args.threadEl);

  try {
    const res = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: args.sessionId, message: text }),
    });

    if (!res.ok || !res.body) {
      throw new Error(`HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const raw = line.slice(6).trim();
        if (raw === "[DONE]") break;

        try {
          const parsed = JSON.parse(raw) as StreamPayload;
          if (parsed.error) throw new Error(parsed.error);
          if (parsed.token) {
            args.messages[args.messages.length - 1].content += parsed.token;
            scrollToBottom(args.threadEl);
          }
        } catch {
          // malformed SSE chunk — skip
        }
      }
    }
  } catch (err) {
    args.messages[args.messages.length - 1].content = `Error: ${
      err instanceof Error ? err.message : "Unknown error"
    }`;
  } finally {
    args.messages[args.messages.length - 1].streaming = false;
    args.setIsStreaming(false);
    scrollToBottom(args.threadEl);
    if (args.onAssistantComplete) {
      await args.onAssistantComplete();
    }
  }
}

export function createSubmitMessage(
  bindings: SubmitMessageBindings,
): () => Promise<void> {
  return async () =>
    sendMessage({
      input: bindings.getInput(),
      isStreaming: bindings.getIsStreaming(),
      sessionId: bindings.sessionId,
      messages: bindings.getMessages(),
      setInput: bindings.setInput,
      setIsStreaming: bindings.setIsStreaming,
      threadEl: bindings.getThreadEl(),
      onAssistantComplete: bindings.onAssistantComplete,
    });
}

export async function fetchSuggestedPlaceholder(
  sessionId: string,
  fallback: string,
): Promise<string> {
  try {
    const response = await fetch("/placeholder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    });
    if (!response.ok) {
      return fallback;
    }

    const payload = (await response.json()) as { placeholder?: string };
    const placeholder = payload.placeholder?.trim();
    if (!placeholder) {
      return fallback;
    }

    return placeholder;
  } catch {
    return fallback;
  }
}

export function handleEnterToSend(
  event: KeyboardEvent,
  onSend: () => void | Promise<void>,
): void {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    void onSend();
  }
}
