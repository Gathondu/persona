<script lang="ts">
  import styles from "./Chat.module.css";
  import {
    createSubmitMessage,
    fetchSuggestedPlaceholder,
    handleEnterToSend,
    renderMarkdown,
    type Message,
  } from "./chat-logic";

  const sessionId = crypto.randomUUID();

  let messages = $state<Message[]>([
    {
      role: "assistant",
      content:
        "Hello, and welcome - I'm Denis.\n\nI'd love to hear a bit about what you're looking for, whether that's a full-time role, contract support, or help solving a specific technical challenge. If you're comfortable, feel free to share your name as well.",
    },
  ]);
  let input = $state("");
  let isStreaming = $state(false);
  let threadEl = $state<HTMLElement | null>(null);
  let inputPlaceholder = $state("Share a quick note about your role or hiring need...");
  let placeholderInitialized = $state(false);

  const canSend = $derived(input.trim().length > 0 && !isStreaming);

  function getFallbackPlaceholder(): string {
    const hasUserMessage = messages.some((message) => message.role === "user");
    if (hasUserMessage) {
      return "Share more context, goals, or questions...";
    }
    return "Share a quick note about your role or hiring need...";
  }

  async function refreshPlaceholder(): Promise<void> {
    inputPlaceholder = await fetchSuggestedPlaceholder(
      sessionId,
      getFallbackPlaceholder(),
    );
  }

  $effect(() => {
    if (placeholderInitialized) {
      return;
    }
    placeholderInitialized = true;
    void refreshPlaceholder();
  });

  const submitMessage = createSubmitMessage({
    getInput: () => input,
    getIsStreaming: () => isStreaming,
    getMessages: () => messages,
    getThreadEl: () => threadEl,
    setInput: (value) => (input = value),
    setIsStreaming: (value) => (isStreaming = value),
    sessionId,
    onAssistantComplete: refreshPlaceholder,
  });
</script>

<div class={styles.shell}>
  <header class={styles.header}>
    <span class={styles.logo}>&#9670;</span>
    <h1 class={styles.title}>Denis Ngugi Gathondu's Chatbot</h1>
  </header>

  <div class={styles.thread} bind:this={threadEl}>
    {#each messages as msg}
      <div class={`${styles.bubble} ${styles[msg.role]}`}>
        <span class={styles.roleLabel}
          >{msg.role === "user" ? "You" : "Denis"}</span
        >
        {#if msg.streaming && !msg.content.trim()}
          <div class={styles.typingIndicator} aria-label="Denis is typing">
            <span class={styles.typingDot}></span>
            <span class={styles.typingDot}></span>
            <span class={styles.typingDot}></span>
          </div>
        {:else}
          <div class={styles.markdown}>
            {@html renderMarkdown(msg.content)}
            {#if msg.streaming}<span class={styles.cursor}>|</span>{/if}
          </div>
        {/if}
      </div>
    {/each}
  </div>

  <form
    class={styles.inputBar}
    onsubmit={(e) => {
      e.preventDefault();
      void submitMessage();
    }}
  >
    <textarea
      class={styles.textarea}
      placeholder={inputPlaceholder}
      rows={1}
      bind:value={input}
      onkeydown={(event) => handleEnterToSend(event, submitMessage)}
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
