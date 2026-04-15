<script lang="ts">
  import styles from "./Chat.module.css";
  import {
    applyDocumentTheme,
    bootstrapChatState,
    mergeWelcomeWithHistory,
    createSubmitMessage,
    DEFAULT_INPUT_PLACEHOLDER,
    fetchHistory,
    fetchSuggestedPlaceholder,
    getFallbackPlaceholder,
    getKnownSessionIds,
    handleEnterToSend,
    loadSidebarOpen,
    loadThemePreference,
    readSystemPrefersDark,
    removeChatSession,
    renderMarkdown,
    saveChatIndex,
    saveSidebarOpen,
    saveThemePreference,
    scrollToBottom,
    setActiveSessionId,
    subscribePrefersColorScheme,
    touchChat,
    tryCreateChat,
    type ChatMeta,
    type Message,
    type ThemePreference,
  } from "./chat-logic";

  async function scrollThreadToBottom(): Promise<void> {
    await scrollToBottom(threadEl);
  }

  const boot = bootstrapChatState();
  let chats = $state<ChatMeta[]>(boot.chats);
  let activeSessionId = $state(boot.activeSessionId);

  let messages = $state<Message[]>(mergeWelcomeWithHistory([]));
  let input = $state("");
  let isStreaming = $state(false);
  let threadEl = $state<HTMLElement | null>(null);
  let inputPlaceholder = $state(DEFAULT_INPUT_PLACEHOLDER);
  let placeholderInitialized = $state(false);
  let chatLimitNotice = $state("");
  let sidebarOpen = $state(loadSidebarOpen());
  let themePreference = $state<ThemePreference>(loadThemePreference());
  let systemPrefersDark = $state(readSystemPrefersDark());

  const effectiveDark = $derived(
    themePreference === "dark" ||
      (themePreference === "system" && systemPrefersDark),
  );

  const canSend = $derived(input.trim().length > 0 && !isStreaming);

  function toggleSidebar(): void {
    sidebarOpen = !sidebarOpen;
    saveSidebarOpen(sidebarOpen);
  }

  function setThemePreference(next: "light" | "dark"): void {
    themePreference = next;
    saveThemePreference(next);
  }

  $effect(() => {
    return subscribePrefersColorScheme((dark) => {
      systemPrefersDark = dark;
    });
  });

  $effect(() => {
    applyDocumentTheme(effectiveDark);
  });

  async function refreshPlaceholder(): Promise<void> {
    inputPlaceholder = await fetchSuggestedPlaceholder(
      activeSessionId,
      getFallbackPlaceholder(messages),
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
      messages = mergeWelcomeWithHistory(history);
      await refreshPlaceholder();
      await scrollThreadToBottom();
    })();
  });

  $effect(() => {
    const text = chatLimitNotice;
    if (!text) {
      return;
    }
    const handle = setTimeout(() => {
      chatLimitNotice = "";
    }, 2000);
    return () => {
      clearTimeout(handle);
    };
  });

  function persistChats(nextChats: ChatMeta[]): void {
    chats = nextChats;
    saveChatIndex(nextChats);
  }

  function handleCreateChat(): void {
    const outcome = tryCreateChat(chats);
    if (!outcome.ok) {
      chatLimitNotice = outcome.notice;
      return;
    }
    chatLimitNotice = "";
    chats = outcome.chats;
    activeSessionId = outcome.newActiveSessionId;
    input = "";
    messages = mergeWelcomeWithHistory([]);
    void scrollThreadToBottom();
  }

  async function handleDeleteChat(sessionId: string): Promise<void> {
    const result = await removeChatSession(sessionId, chats, activeSessionId);
    chats = result.chats;
    activeSessionId = result.activeSessionId;
    if (result.clearInput) {
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
  <div
    class={`${styles.layout} ${sidebarOpen ? "" : styles.layoutSidebarCollapsed}`}
  >
    <aside id="chat-sidebar" class={styles.sidebar} inert={!sidebarOpen}>
      <button
        class={styles.newChatBtn}
        type="button"
        onclick={handleCreateChat}
      >
        + New chat
      </button>
      <div class={styles.chatList}>
        {#each chats as chat}
          <div
            class={`${styles.chatItem} ${chat.sessionId === activeSessionId ? styles.chatItemActive : ""}`}
          >
            <button
              class={styles.chatSwitchBtn}
              type="button"
              aria-current={chat.sessionId === activeSessionId
                ? "true"
                : undefined}
              onclick={() => {
                chatLimitNotice = "";
                activeSessionId = chat.sessionId;
              }}
            >
              <span class={styles.chatSwitchIcon} aria-hidden="true">
                <svg
                  width="18"
                  height="18"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                >
                  <path
                    d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"
                  ></path>
                </svg>
              </span>
              <span class={styles.chatSwitchLabel}>{chat.title}</span>
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
      <div class={styles.themeRow}>
        <span class={styles.themeLabel} id="theme-toggle-label">Theme</span>
        <div
          class={styles.themeToggle}
          role="group"
          aria-labelledby="theme-toggle-label"
        >
          <button
            type="button"
            class={`${styles.themeOption} ${themePreference === "light" ? styles.themeOptionActive : ""}`}
            aria-pressed={themePreference === "light"}
            title="Light theme"
            onclick={() => setThemePreference("light")}
          >
            <span class={styles.srOnly}>Light theme</span>
            <svg
              class={styles.themeIcon}
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <circle cx="12" cy="12" r="4"></circle>
              <path
                d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"
              ></path>
            </svg>
          </button>
          <button
            type="button"
            class={`${styles.themeOption} ${themePreference === "dark" ? styles.themeOptionActive : ""}`}
            aria-pressed={themePreference === "dark"}
            title="Dark theme"
            onclick={() => setThemePreference("dark")}
          >
            <span class={styles.srOnly}>Dark theme</span>
            <svg
              class={styles.themeIcon}
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
            </svg>
          </button>
        </div>
      </div>
    </aside>

    <div class={styles.mainColumn}>
      <header class={styles.header}>
        <button
          class={styles.sidebarToggle}
          type="button"
          onclick={toggleSidebar}
          aria-expanded={sidebarOpen}
          aria-controls="chat-sidebar"
          title={sidebarOpen ? "Hide conversations" : "Show conversations"}
        >
          <span class={styles.srOnly}>
            {sidebarOpen ? "Hide conversation list" : "Show conversation list"}
          </span>
          <svg
            width="22"
            height="22"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <rect x="3" y="4" width="7" height="16" rx="1"></rect>
            <line x1="14" y1="8" x2="21" y2="8"></line>
            <line x1="14" y1="12" x2="21" y2="12"></line>
            <line x1="14" y1="16" x2="21" y2="16"></line>
          </svg>
        </button>
        <h1 class={styles.title}>Denis Ngugi Gathondu</h1>
      </header>

      <div class={styles.chatPane}>
        <div class={styles.thread} bind:this={threadEl}>
          {#each messages as msg}
            <div class={`${styles.bubble} ${styles[msg.role]}`}>
              <span class={styles.roleLabel}
                >{msg.role === "user" ? "You" : "Denis"}</span
              >
              {#if msg.streaming && !msg.content.trim()}
                <div
                  class={styles.typingIndicator}
                  aria-label="Denis is typing"
                >
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

        <div class={styles.inputDock}>
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
  </div>

  {#if chatLimitNotice}
    <div class={styles.toastHost}>
      <p class={styles.toast} role="status" aria-live="polite">
        {chatLimitNotice}
      </p>
    </div>
  {/if}
</div>
