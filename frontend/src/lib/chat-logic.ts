import DOMPurify from "dompurify";
import { marked } from "marked";
import { tick } from "svelte";

export const MAX_CHATS = 3;
const CHAT_INDEX_KEY = "dng_chat_index_v1";
const ACTIVE_CHAT_KEY = "dng_active_chat_v1";

export interface Message {
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
}

export interface ChatMeta {
  sessionId: string;
  title: string;
  updatedAt: number;
}

interface StreamPayload {
  token?: string;
  error?: string;
}

interface SendMessageArgs {
  input: string;
  isStreaming: boolean;
  sessionId: string;
  knownSessionIds: string[];
  messages: Message[];
  setInput: (value: string) => void;
  setIsStreaming: (value: boolean) => void;
  threadEl: HTMLElement | null;
  onAssistantComplete?: () => void | Promise<void>;
  onUserMessage?: (message: string) => void;
}

interface SubmitMessageBindings {
  getInput: () => string;
  getIsStreaming: () => boolean;
  getSessionId: () => string;
  getKnownSessionIds: () => string[];
  getMessages: () => Message[];
  getThreadEl: () => HTMLElement | null;
  setInput: (value: string) => void;
  setIsStreaming: (value: boolean) => void;
  onAssistantComplete?: () => void | Promise<void>;
  onUserMessage?: (message: string) => void;
}

marked.setOptions({
  breaks: true,
  gfm: true,
});

export function renderMarkdown(content: string): string {
  const html = marked.parse(content, { async: false });
  return DOMPurify.sanitize(html);
}

export async function scrollToBottom(threadEl: HTMLElement | null): Promise<void> {
  await tick();
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
  if (args.onUserMessage) {
    args.onUserMessage(text);
  }

  args.messages.push({ role: "user", content: text });
  args.messages.push({ role: "assistant", content: "", streaming: true });
  await scrollToBottom(args.threadEl);

  try {
    const res = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: args.sessionId,
        message: text,
        known_session_ids: args.knownSessionIds,
      }),
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
            await scrollToBottom(args.threadEl);
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
    await scrollToBottom(args.threadEl);
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
      sessionId: bindings.getSessionId(),
      knownSessionIds: bindings.getKnownSessionIds(),
      messages: bindings.getMessages(),
      setInput: bindings.setInput,
      setIsStreaming: bindings.setIsStreaming,
      threadEl: bindings.getThreadEl(),
      onAssistantComplete: bindings.onAssistantComplete,
      onUserMessage: bindings.onUserMessage,
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

function parseChatIndex(raw: string | null): ChatMeta[] {
  if (!raw) {
    return [];
  }
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) {
      return [];
    }
    const chats: ChatMeta[] = [];
    for (const item of parsed) {
      if (
        typeof item === "object" &&
        item !== null &&
        "sessionId" in item &&
        "title" in item &&
        "updatedAt" in item &&
        typeof item.sessionId === "string" &&
        typeof item.title === "string" &&
        typeof item.updatedAt === "number"
      ) {
        chats.push({
          sessionId: item.sessionId,
          title: item.title,
          updatedAt: item.updatedAt,
        });
      }
    }
    chats.sort((a, b) => b.updatedAt - a.updatedAt);
    return chats;
  } catch {
    return [];
  }
}

export function loadChatIndex(): ChatMeta[] {
  return parseChatIndex(localStorage.getItem(CHAT_INDEX_KEY));
}

export function saveChatIndex(chats: ChatMeta[]): void {
  localStorage.setItem(CHAT_INDEX_KEY, JSON.stringify(chats));
}

export function getActiveSessionId(): string | null {
  const active = localStorage.getItem(ACTIVE_CHAT_KEY);
  if (!active || !active.trim()) {
    return null;
  }
  return active;
}

export function setActiveSessionId(sessionId: string): void {
  localStorage.setItem(ACTIVE_CHAT_KEY, sessionId);
}

export function createChat(
  chats: ChatMeta[],
  title = "New conversation",
): { ok: true; chats: ChatMeta[]; created: ChatMeta } | { ok: false } {
  if (chats.length >= MAX_CHATS) {
    return { ok: false };
  }
  const created: ChatMeta = {
    sessionId: crypto.randomUUID(),
    title,
    updatedAt: Date.now(),
  };
  const next = [created, ...chats].sort((a, b) => b.updatedAt - a.updatedAt);
  return { ok: true, chats: next, created };
}

export function touchChat(chats: ChatMeta[], sessionId: string, latestText: string): ChatMeta[] {
  const trimmed = latestText.trim();
  return chats
    .map((chat) => {
      if (chat.sessionId !== sessionId) {
        return chat;
      }
      const maybeTitle = chat.title === "New conversation" && trimmed
        ? trimmed.slice(0, 42)
        : chat.title;
      return {
        ...chat,
        title: maybeTitle || "New conversation",
        updatedAt: Date.now(),
      };
    })
    .sort((a, b) => b.updatedAt - a.updatedAt);
}

export function removeChat(chats: ChatMeta[], sessionId: string): ChatMeta[] {
  return chats.filter((chat) => chat.sessionId !== sessionId);
}

export function getKnownSessionIds(chats: ChatMeta[], activeSessionId: string): string[] {
  return chats
    .map((chat) => chat.sessionId)
    .filter((id) => id !== activeSessionId);
}

export async function fetchHistory(sessionId: string): Promise<Message[]> {
  try {
    const response = await fetch(`/history/${sessionId}`);
    if (!response.ok) {
      return [];
    }
    const payload = (await response.json()) as Array<{ role?: string; content?: string }>;
    const messages: Message[] = [];
    for (const item of payload) {
      if (item.role === "user" || item.role === "assistant") {
        messages.push({
          role: item.role,
          content: typeof item.content === "string" ? item.content : "",
        });
      }
    }
    return messages;
  } catch {
    return [];
  }
}

export async function deleteSessionOnServer(sessionId: string): Promise<boolean> {
  try {
    const response = await fetch(`/sessions/${sessionId}`, { method: "DELETE" });
    return response.ok;
  } catch {
    return false;
  }
}

// --- Sidebar / theme (localStorage + document) ---

export const SIDEBAR_OPEN_KEY = "dng_sidebar_open_v1";
export const THEME_KEY = "dng_theme_v1";

export type ThemePreference = "light" | "dark" | "system";

export function readSystemPrefersDark(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
  );
}

export function loadSidebarOpen(): boolean {
  if (typeof localStorage === "undefined") {
    return true;
  }
  const raw = localStorage.getItem(SIDEBAR_OPEN_KEY);
  if (raw === null) {
    return true;
  }
  return raw === "1";
}

export function saveSidebarOpen(open: boolean): void {
  if (typeof localStorage === "undefined") {
    return;
  }
  localStorage.setItem(SIDEBAR_OPEN_KEY, open ? "1" : "0");
}

export function loadThemePreference(): ThemePreference {
  if (typeof localStorage === "undefined") {
    return "system";
  }
  const raw = localStorage.getItem(THEME_KEY);
  if (raw === "light" || raw === "dark") {
    return raw;
  }
  return "system";
}

export function saveThemePreference(next: "light" | "dark"): void {
  if (typeof localStorage === "undefined") {
    return;
  }
  localStorage.setItem(THEME_KEY, next);
}

/** Subscribe to OS color scheme; calls listener immediately; returns unsubscribe. */
export function subscribePrefersColorScheme(
  listener: (prefersDark: boolean) => void,
): () => void {
  if (typeof window === "undefined") {
    return () => {};
  }
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  const onChange = (): void => {
    listener(mq.matches);
  };
  onChange();
  mq.addEventListener("change", onChange);
  return () => {
    mq.removeEventListener("change", onChange);
  };
}

export function applyDocumentTheme(isDark: boolean): void {
  if (typeof document === "undefined") {
    return;
  }
  const root = document.documentElement;
  if (isDark) {
    root.dataset.theme = "dark";
  } else {
    delete root.dataset.theme;
  }
}

// --- Welcome copy & placeholders ---

export const WELCOME_CONTENT =
  "**Hello, and welcome!**<br><br>I'm ***Denis***—software engineer by day, overthinker by night, and apparently a chatbot now, which is either very on-brand or a cry for help. I haven't decided yet.<br><br>Tell me what you're working on. I'll think about it far more than is strictly necessary, and then we'll figure it out together."

export function buildWelcomeMessages(): Message[] {
  return [{ role: "assistant", content: WELCOME_CONTENT }];
}

export const DEFAULT_INPUT_PLACEHOLDER =
  "Share a quick note about your role or hiring need...";

export function getFallbackPlaceholder(messages: Message[]): string {
  const hasUserMessage = messages.some((message) => message.role === "user");
  if (hasUserMessage) {
    return "Share more context, goals, or questions...";
  }
  return DEFAULT_INPUT_PLACEHOLDER;
}

// --- Initial session list (persist + return for UI state) ---

export function bootstrapChatState(): { chats: ChatMeta[]; activeSessionId: string } {
  const storedChats = loadChatIndex();
  const initialChatList: ChatMeta[] =
    storedChats.length > 0
      ? storedChats
      : [
          {
            sessionId: crypto.randomUUID(),
            title: "New conversation",
            updatedAt: Date.now(),
          },
        ];
  const storedActiveSession = getActiveSessionId();
  const initialActiveSession =
    storedActiveSession &&
    initialChatList.some((chat) => chat.sessionId === storedActiveSession)
      ? storedActiveSession
      : initialChatList[0].sessionId;

  saveChatIndex(initialChatList);
  setActiveSessionId(initialActiveSession);

  return { chats: initialChatList, activeSessionId: initialActiveSession };
}

// --- Create / delete chat flows ---

export type CreateChatOutcome =
  | { ok: false; notice: string }
  | { ok: true; chats: ChatMeta[]; newActiveSessionId: string };

export function tryCreateChat(currentChats: ChatMeta[]): CreateChatOutcome {
  const created = createChat(currentChats);
  if (!created.ok) {
    return {
      ok: false,
      notice: `You can only keep ${MAX_CHATS} chats. Delete one to create another.`,
    };
  }
  saveChatIndex(created.chats);
  setActiveSessionId(created.created.sessionId);
  return {
    ok: true,
    chats: created.chats,
    newActiveSessionId: created.created.sessionId,
  };
}

export interface RemoveChatSessionResult {
  chats: ChatMeta[];
  activeSessionId: string;
  clearInput: boolean;
}

export async function removeChatSession(
  sessionId: string,
  chats: ChatMeta[],
  activeSessionId: string,
): Promise<RemoveChatSessionResult> {
  await deleteSessionOnServer(sessionId);
  const remaining = removeChat(chats, sessionId);
  if (remaining.length === 0) {
    const fresh = createChat([]);
    if (!fresh.ok) {
      return { chats: [], activeSessionId, clearInput: true };
    }
    saveChatIndex(fresh.chats);
    setActiveSessionId(fresh.created.sessionId);
    return {
      chats: fresh.chats,
      activeSessionId: fresh.created.sessionId,
      clearInput: true,
    };
  }
  saveChatIndex(remaining);
  const nextActive =
    sessionId === activeSessionId ? remaining[0].sessionId : activeSessionId;
  if (nextActive !== activeSessionId) {
    setActiveSessionId(nextActive);
  }
  return {
    chats: remaining,
    activeSessionId: nextActive,
    clearInput: sessionId === activeSessionId,
  };
}
