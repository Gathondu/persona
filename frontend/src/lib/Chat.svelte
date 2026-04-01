<script lang="ts">
  import styles from "./Chat.module.css";
  import {
    createSubmitMessage,
    handleEnterToSend,
    renderMarkdown,
    type Message,
  } from "./chat-logic";

  const sessionId = crypto.randomUUID();

  let messages = $state<Message[]>([]);
  let input = $state("");
  let isStreaming = $state(false);
  let threadEl = $state<HTMLElement | null>(null);

  const canSend = $derived(input.trim().length > 0 && !isStreaming);
  const submitMessage = createSubmitMessage({
    getInput: () => input,
    getIsStreaming: () => isStreaming,
    getMessages: () => messages,
    getThreadEl: () => threadEl,
    setInput: (value) => (input = value),
    setIsStreaming: (value) => (isStreaming = value),
    sessionId,
  });
</script>

<div class={styles.shell}>
  <header class={styles.header}>
    <span class={styles.logo}>&#9670;</span>
    <h1 class={styles.title}>Denis Ngugi Gathondu's Chatbot</h1>
  </header>

  <div class={styles.thread} bind:this={threadEl}>
    {#if messages.length === 0}
      <div class={styles.empty}>
        <div class={`${styles.bubble} ${styles.assistant} ${styles.starterBubble}`}>
          <span class={styles.roleLabel}>Denis</span>
          <div class={styles.markdown}>
            <p>Hi there - how are you today, and what is your name?</p>
          </div>
        </div>
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
      void submitMessage();
    }}
  >
    <textarea
      class={styles.textarea}
      placeholder="Ask away..."
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
