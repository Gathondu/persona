<script lang="ts">
  import styles from "./Chat.module.css";
  import {
    createSubmitMessage,
    createChat,
    deleteSessionOnServer,
    fetchHistory,
    fetchSuggestedPlaceholder,
    getActiveSessionId,
    getKnownSessionIds,
    handleEnterToSend,
    loadChatIndex,
    removeChat,
    renderMarkdown,
    saveChatIndex,
    setActiveSessionId,
    touchChat,
    MAX_CHATS,
    type ChatMeta,
    type Message,
  } from "./chat-logic";

  const WELCOME_CONTENT =
    "Hello, and welcome - I'm Denis.\n\nI'd love to hear a bit about what you're looking for, whether that's a full-time role, contract support, or help solving a specific technical challenge. If you're comfortable, feel free to share your name as well.";

  function buildWelcomeMessages(): Message[] {
    return [{ role: "assistant", content: WELCOME_CONTENT }];
  }

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

  let chats = $state<ChatMeta[]>(initialChatList);
  let activeSessionId = $state(initialActiveSession);

  let messages = $state<Message[]>(buildWelcomeMessages());
  let input = $state("");
  let isStreaming = $state(false);
  let threadEl = $state<HTMLElement | null>(null);
  let inputPlaceholder = $state("Share a quick note about your role or hiring need...");
  let placeholderInitialized = $state(false);
  let chatLimitNotice = $state("");

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
      activeSessionId,
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

  $effect(() => {
    const current = activeSessionId;
    setActiveSessionId(current);
    void (async () => {
      const history = await fetchHistory(current);
      messages = history.length > 0 ? history : buildWelcomeMessages();
      await refreshPlaceholder();
    })();
  });

  function persistChats(nextChats: ChatMeta[]): void {
    chats = nextChats;
    saveChatIndex(nextChats);
  }

  function handleCreateChat(): void {
    const created = createChat(chats);
    if (!created.ok) {
      chatLimitNotice = `You can only keep ${MAX_CHATS} chats. Delete one to create another.`;
      return;
    }
    chatLimitNotice = "";
    persistChats(created.chats);
    activeSessionId = created.created.sessionId;
    input = "";
    messages = buildWelcomeMessages();
  }

  async function handleDeleteChat(sessionId: string): Promise<void> {
    await deleteSessionOnServer(sessionId);
    const remaining = removeChat(chats, sessionId);
    if (remaining.length === 0) {
      const fresh = createChat([]);
      if (fresh.ok) {
        persistChats(fresh.chats);
        activeSessionId = fresh.created.sessionId;
      }
      return;
    }
    persistChats(remaining);
    if (sessionId === activeSessionId) {
      activeSessionId = remaining[0].sessionId;
      input = "";
    }
  }

  const submitMessage = createSubmitMessage({
    getInput: () => input,
    getIsStreaming: () => isStreaming,
    getSessionId: () => activeSessionId,
    getKnownSessionIds: () => getKnownSessionIds(chats, activeSessionId),
    getMessages: () => messages,
    getThreadEl: () => threadEl,
    setInput: (value) => (input = value),
    setIsStreaming: (value) => (isStreaming = value),
    onUserMessage: (text) => {
      persistChats(touchChat(chats, activeSessionId, text));
    },
    onAssistantComplete: refreshPlaceholder,
  });
</script>

<div class={styles.shell}>
  <header class={styles.header}>
    <span class={styles.logo}>&#9670;</span>
    <h1 class={styles.title}>Denis Ngugi Gathondu's Chatbot</h1>
  </header>

  <div class={styles.body}>
    <aside class={styles.sidebar}>
      <button class={styles.newChatBtn} type="button" onclick={handleCreateChat}>
        + New chat
      </button>
      {#if chatLimitNotice}
        <p class={styles.limitNotice}>{chatLimitNotice}</p>
      {/if}
      <div class={styles.chatList}>
        {#each chats as chat}
          <div class={`${styles.chatItem} ${chat.sessionId === activeSessionId ? styles.chatItemActive : ""}`}>
            <button
              class={styles.chatSwitchBtn}
              type="button"
              onclick={() => {
                chatLimitNotice = "";
                activeSessionId = chat.sessionId;
              }}
            >
              {chat.title}
            </button>
            <button
              class={styles.chatDeleteBtn}
              type="button"
              aria-label="Delete chat"
              onclick={() => void handleDeleteChat(chat.sessionId)}
            >
              x
            </button>
          </div>
        {/each}
      </div>
    </aside>

    <div class={styles.chatPane}>
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
  </div>
</div>
