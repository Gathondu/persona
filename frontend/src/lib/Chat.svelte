<script lang="ts">
  import DOMPurify from "dompurify";
  import { marked } from "marked";
  import styles from "./Chat.module.css";

  interface Message {
    role: "user" | "assistant";
    content: string;
    streaming?: boolean;
  }

  const sessionId = crypto.randomUUID();

  let messages = $state<Message[]>([]);
  let input = $state("");
  let isStreaming = $state(false);
  let threadEl = $state<HTMLElement | null>(null);

  const canSend = $derived(input.trim().length > 0 && !isStreaming);

  marked.setOptions({
    breaks: true,
    gfm: true,
  });

  function renderMarkdown(content: string): string {
    const html = marked.parse(content, { async: false });
    return DOMPurify.sanitize(html);
  }

  function scrollToBottom() {
    if (threadEl) {
      threadEl.scrollTop = threadEl.scrollHeight;
    }
  }

  async function sendMessage() {
    const text = input.trim();
    if (!text || isStreaming) return;

    input = "";
    isStreaming = true;

    messages.push({ role: "user", content: text });
    messages.push({ role: "assistant", content: "", streaming: true });

    scrollToBottom();

    try {
      const res = await fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, message: text }),
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
            const parsed = JSON.parse(raw) as {
              token?: string;
              error?: string;
            };
            if (parsed.error) throw new Error(parsed.error);
            if (parsed.token) {
              messages[messages.length - 1].content += parsed.token;
              scrollToBottom();
            }
          } catch {
            // malformed SSE chunk — skip
          }
        }
      }
    } catch (err) {
      messages[messages.length - 1].content =
        `Error: ${err instanceof Error ? err.message : "Unknown error"}`;
    } finally {
      messages[messages.length - 1].streaming = false;
      isStreaming = false;
      scrollToBottom();
    }
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }
</script>

<div class={styles.shell}>
  <header class={styles.header}>
    <span class={styles.logo}>&#9670;</span>
    <h1 class={styles.title}>Denis Ngugi Gathondu's Chatbot</h1>
  </header>

  <div class={styles.thread} bind:this={threadEl}>
    {#if messages.length === 0}
      <div class={styles.empty}>
        <p>Start a conversation with Denis.</p>
      </div>
    {/if}
    {#each messages as msg}
      <div class={`${styles.bubble} ${styles[msg.role]}`}>
        <span class={styles.roleLabel}
          >{msg.role === "user" ? "You" : "Denis"}</span
        >
        <div class={styles.markdown}>
          {@html renderMarkdown(msg.content)}
          {#if msg.streaming}<span class={styles.cursor}>▌</span>{/if}
        </div>
      </div>
    {/each}
  </div>

  <form
    class={styles.inputBar}
    onsubmit={(e) => {
      e.preventDefault();
      sendMessage();
    }}
  >
    <textarea
      class={styles.textarea}
      placeholder="Ask away..."
      rows={1}
      bind:value={input}
      onkeydown={handleKeydown}
      disabled={isStreaming}
    ></textarea>
    <button
      class={styles.sendBtn}
      type="submit"
      disabled={!canSend}
      aria-label="Send"
    >
      <svg
        width="20"
        height="20"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2.5"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <line x1="22" y1="2" x2="11" y2="13"></line>
        <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
      </svg>
    </button>
  </form>
</div>
