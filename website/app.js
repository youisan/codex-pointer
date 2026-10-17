(() => {
  "use strict";
  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => [...document.querySelectorAll(selector)];
  const copy = {
    en: {
      skip: "Skip to content",
      navLabel: "Main navigation",
      navHow: "How it works",
      navFeatures: "Features",
      navInstall: "Install",
      heroOne: "Point at it.",
      heroTwo: "Bring it to Codex.",
      heroBody:
        "Windows, folders, files. One small button to bring what you’re working on into the conversation.",
      download: "Download for Windows",
      github: "View on GitHub",
      heroCaption: "Windows preview · Free and open source",
      nativeLanguage:
        "Desktop language follows Codex: English / Simplified Chinese; other languages use English.",
      demoLabel: "Interactive product preview",
      demoTabs: "Example target",
      folder: "Folder",
      window: "Window",
      breadcrumb: "Projects / Research",
      search: "Search",
      name: "Name",
      modified: "Date modified",
      type: "Type",
      buildOutput: "Build output",
      windowHint: "Bring the window context into your next question.",
      togglePanel: "Toggle example panel",
      panelLabel: "Example task panel",
      closePanel: "Close example panel",
      chatChoice: "Example conversation",
      newChat: "New chat",
      continueChat: "Continue chat",
      linkedChat: "Linked: Research planning",
      taskLabel: "Example task",
      includeScreenshot: "Include screenshot",
      continueInCodex: "Continue in Codex",
      sendToChat: "Send to linked chat",
      selectTarget: "Select a target",
      openPanel: "Open panel",
      demoNote:
        "Website preview only. The desktop interface follows Codex's language. Nothing is captured or sent.",
      howHeading: "A shorter path to the conversation.",
      howIntro: "Keep your focus. Let the context come with you.",
      stepOneTitle: "Point to your target",
      stepOneBody:
        "Drag the button onto a window or folder, or drop one local file or folder onto it. Release to select; the panel stays closed.",
      stepTwoTitle: "Say what you need",
      stepTwoBody:
        "Click the circle to open your selected target. Choose a chat and write a task, or use a shortcut. Click again to collapse.",
      stepThreeTitle: "Continue in Codex",
      stepThreeBody:
        "For a new chat, review and send the draft in Codex. For a linked chat, submit explicitly in Pointer to queue the task.",
      miniTask: "Help me understand this folder.",
      keyOpen: "to open",
      keyCancel: "to cancel",
      featureHeading: "Less setup. More momentum.",
      targetContext: "Example target",
      sampleFolder: "Folder · Research",
      sampleFile: "File · Brief.md",
      sampleWindow: "Window · Build output",
      researchChat: "Research planning",
      explicitLink: "Explicitly linked",
      editableTask: "Task · editable",
      clearTask: "Clear",
      shortcutLabel: "Example task shortcuts",
      shortcutPlaceholder:
        "Choose a shortcut to start. Your draft stays editable.",
      tryFile: "Try a single-file target",
      shortcutsNote: "Shortcuts only add to a draft. They never send it.",
      featureDemoNote:
        "A real companion for your desktop. This website preview never accesses your files.",
      featureOneTitle: "A chat for each context",
      featureOneBody:
        "Return to a folder or app and pick up the chat you explicitly linked.",
      featureTwoTitle: "Start with a useful task",
      featureTwoBody:
        "Context-aware shortcuts add a starting point. Your draft stays yours.",
      featureThreeTitle: "Only what you choose",
      featureThreeBody:
        "Optional screenshots with a preview. No background screen or clipboard capture.",
      installHeading: "Make room for one small button.",
      platform: "Windows 10 / 11 · 64-bit preview",
      installBody:
        "Download the complete plugin package. The desktop helper is included; no Python setup needed.",
      downloadPackage: "Download Windows package",
      releaseNotes: "Release notes",
      installOneTitle: "Download and unzip",
      installOneBody: "Keep the plugin folder and its bundled files together.",
      installTwoTitle: "Install the local plugin",
      commandIntro:
        "In a terminal, open the unzipped codex-pointer folder and run:",
      installThreeTitle: "Open it from Codex",
      installThreeBody:
        "Reload Codex. Find Codex Pointer in Explore, then show the button. Pin its entry if you like.",
      copy: "Copy",
      copied: "Commands copied.",
      copyFallback: "Commands selected. Press Ctrl+C to copy them.",
      boundariesTitle: "Preview boundaries",
      boundariesBody:
        "New chats open as drafts for you to send. Existing chats keep their own tools and permissions. Software actions depend on the tools enabled in Codex.",
      requirements:
        "Requires Codex installed and signed in, with a supported Codex CLI available. This is a Windows preview; some Explorer, display and permission combinations still need testing.",
      independent: "Independent project. Not affiliated with OpenAI.",
      footerNav: "Project links",
      license: "MIT license",
      draftFolder: "Help me make sense of this folder.",
      draftFile: "Summarize the key points in this file.",
      draftWindow: "Help me understand this error.",
      demoContinue:
        "Preview only. In the desktop app, a new chat opens as a draft for you to review and send.",
      demoExisting:
        "Preview only. In the desktop app, continuing queues your task to the chat you explicitly linked.",
      screenshotNote: "Preview only — no screenshot is taken on this website.",
      shortcutAdded: "Added to your draft. Nothing was sent.",
      shortcutDuplicate: "This shortcut is already in your draft.",
      contextChanged: "Target changed. Your existing draft was kept.",
      targetSelected:
        "Example target selected. Click the circle to open or collapse the panel; your target and draft stay in place.",
      dropNote:
        "This website does not read files. On the desktop, dropping one file or folder selects it and keeps the panel closed. Click the circle to open it.",
      metaDescription:
        "A small Windows button that brings your selected window, folder or file into Codex. Independent, free and open source.",
    },
    zh: {
      skip: "跳到主要内容",
      navLabel: "主要导航",
      navHow: "使用方式",
      navFeatures: "实用功能",
      navInstall: "下载安装",
      heroOne: "指向眼前，",
      heroTwo: "就能开始对话。",
      heroBody:
        "窗口、文件夹、文件。用一个小按钮，把正在处理的内容带进 Codex 对话。",
      download: "下载 Windows 版",
      github: "查看 GitHub",
      heroCaption: "Windows 预览版 · 免费开源",
      nativeLanguage:
        "桌面跟随 Codex 的 English / 简体中文设置，其他语言使用英文。",
      demoLabel: "产品交互演示",
      demoTabs: "示例对象",
      folder: "文件夹",
      window: "窗口",
      breadcrumb: "项目 / 研究资料",
      search: "搜索",
      name: "名称",
      modified: "修改日期",
      type: "类型",
      buildOutput: "构建输出",
      windowHint: "把窗口上下文带进下一个问题。",
      togglePanel: "展开或收起示例面板",
      panelLabel: "示例任务面板",
      closePanel: "收起示例面板",
      chatChoice: "示例对话选择",
      newChat: "新对话",
      continueChat: "继续对话",
      linkedChat: "已绑定：研究计划",
      taskLabel: "示例任务",
      includeScreenshot: "附带截图",
      continueInCodex: "在 Codex 中继续",
      sendToChat: "发送到已绑定对话",
      selectTarget: "切换对象",
      openPanel: "展开面板",
      demoNote:
        "仅为网页演示。桌面界面跟随 Codex 语言；此处不采集内容或发送任务。",
      howHeading: "让眼前的内容，更快进入对话。",
      howIntro: "专注手头的事，把上下文交给小按钮。",
      stepOneTitle: "指向你要处理的对象",
      stepOneBody:
        "把按钮拖到窗口或文件夹上，或把一个本地文件、文件夹拖到按钮上。松开只选中目标，面板保持收起。",
      stepTwoTitle: "写下你想做什么",
      stepTwoBody:
        "点击圆圈展开已选目标，选择对话、输入需求，或使用快捷任务。再次点击圆圈收起面板。",
      stepThreeTitle: "确认后，继续处理",
      stepThreeBody:
        "新对话需在 Codex 中检查并发送草稿；已绑定对话则在 Pointer 明确提交后，把任务加入该对话队列。",
      miniTask: "帮我了解这个文件夹。",
      keyOpen: "唤起面板",
      keyCancel: "取消选择",
      featureHeading: "少些准备，顺手接着做。",
      targetContext: "示例对象",
      sampleFolder: "文件夹 · Research",
      sampleFile: "文件 · Brief.md",
      sampleWindow: "窗口 · 构建输出",
      researchChat: "研究计划",
      explicitLink: "明确绑定",
      editableTask: "任务 · 可以编辑",
      clearTask: "清空",
      shortcutLabel: "示例快捷任务",
      shortcutPlaceholder: "选一个快捷任务开始，内容仍然可以编辑。",
      tryFile: "试试单个文件对象",
      shortcutsNote: "快捷任务只追加到草稿，不会发送。",
      featureDemoNote: "桌面上的小帮手。此网页演示不会访问你的文件。",
      featureOneTitle: "每个对象，接回自己的对话",
      featureOneBody: "重新选中同一文件夹或软件，恢复你曾明确绑定的对话。",
      featureTwoTitle: "常用需求，少打几行字",
      featureTwoBody: "快捷任务随对象变化，追加到已有草稿。写好的内容会保留。",
      featureThreeTitle: "只带上你选择的内容",
      featureThreeBody:
        "截图按需勾选，发送前可以预览。不在后台截屏，也不读取剪贴板。",
      installHeading: "给一个小按钮，留个位置。",
      platform: "Windows 10 / 11 · 64 位预览版",
      installBody:
        "下载完整插件包，桌面辅助程序已经包含在内，无需另外配置 Python。",
      downloadPackage: "下载 Windows 插件包",
      releaseNotes: "版本说明",
      installOneTitle: "下载并解压",
      installOneBody: "保留完整目录，插件与附带的文件需要放在一起。",
      installTwoTitle: "安装本地插件",
      commandIntro: "在终端进入解压后的 codex-pointer 目录，运行：",
      installThreeTitle: "从 Codex 打开",
      installThreeBody:
        "重新加载 Codex，在“探索”中找到 Codex Pointer，点击显示按钮。也可以把入口固定到侧边栏。",
      copy: "复制",
      copied: "已复制安装命令。",
      copyFallback: "命令已选中，请按 Ctrl+C 复制。",
      boundariesTitle: "预览版的使用边界",
      boundariesBody:
        "新对话会打开预填草稿，由你确认发送。已有对话保留自己的工具和权限。软件操作能力取决于 Codex 对话中已启用的工具。",
      requirements:
        "需已安装并登录 Codex，并有可用且支持相关命令的 Codex CLI。当前为 Windows 预览版，部分资源管理器、屏幕和权限组合仍需验证。",
      independent: "独立开源项目，与 OpenAI 无隶属关系。",
      footerNav: "项目链接",
      license: "MIT 许可证",
      draftFolder: "帮我了解这个文件夹的主要内容。",
      draftFile: "请总结这个文件的主要内容和重点。",
      draftWindow: "帮我分析这个窗口中的报错。",
      demoContinue: "仅为演示。桌面插件会打开新对话草稿，需你检查并发送。",
      demoExisting: "仅为演示。桌面插件会把任务排队发送到你明确绑定的对话。",
      screenshotNote: "仅为演示，此网页不会截屏。",
      shortcutAdded: "已追加到草稿，没有发送。",
      shortcutDuplicate: "这条快捷任务已在草稿中。",
      contextChanged: "对象已切换，原有草稿已保留。",
      targetSelected:
        "示例对象已选中。点击圆圈展开或收起面板，目标和草稿会保留。",
      dropNote:
        "此网页不读取文件。桌面按钮收到一个文件或文件夹后只选中目标、保持面板收起；点击圆圈再展开。",
      metaDescription:
        "用一个 Windows 浮动按钮，把选中的窗口、文件夹或文件带进 Codex 对话。独立、免费、开源。",
    },
  };
  const taskSets = {
    folder: [
      {
        key: "folder-overview",
        en: "Folder overview",
        zh: "目录概览",
        prompt: {
          en: "First outline this folder’s structure and main contents, and explain what each part is for.",
          zh: "请先梳理这个文件夹的目录结构和主要内容，说明各部分的用途。",
        },
      },
      {
        key: "folder-review",
        en: "Find issues",
        zh: "查找问题",
        prompt: {
          en: "First look at this folder’s structure, then review the relevant contents. Point out obvious issues and suggest how to investigate.",
          zh: "请先查看这个文件夹的结构，再检查相关内容，指出明显问题并给出排查建议。",
        },
      },
      {
        key: "folder-organize",
        en: "Organize",
        zh: "整理建议",
        prompt: {
          en: "Suggest an organization plan based on this folder’s existing contents. Explain your suggestions first; do not move or delete files.",
          zh: "请根据这个文件夹的现有内容给出整理方案，先说明建议，不直接移动或删除文件。",
        },
      },
    ],
    file: [
      {
        key: "file-summary",
        en: "Summarize",
        zh: "总结内容",
        prompt: {
          en: "Read this file and summarize its main contents and key points. If the format cannot be read, explain what information is needed.",
          zh: "请阅读这个文件，概括主要内容和重点；若格式无法读取，请说明需要哪些信息。",
        },
      },
      {
        key: "file-review",
        en: "Check issues",
        zh: "检查问题",
        prompt: {
          en: "Review this file, point out obvious issues or missing information, and suggest improvements.",
          zh: "请检查这个文件，指出明显问题或需要补充的内容，并给出修改建议。",
        },
      },
      {
        key: "file-explain",
        en: "Explain details",
        zh: "解释细节",
        prompt: {
          en: "Explain the important details in this file in clear language. If more context is needed, say so first.",
          zh: "请用清楚易懂的语言解释这个文件中值得关注的细节；需要更多背景时请先说明。",
        },
      },
    ],
    window: [
      {
        key: "window-summary",
        en: "Summarize",
        zh: "总结内容",
        prompt: {
          en: "Summarize the main information available in the selected window. If there is not enough information, explain what else is needed.",
          zh: "请结合选中窗口中可访问的内容，概括主要信息；若信息不足，请说明还需要什么。",
        },
      },
      {
        key: "window-error",
        en: "Explain error",
        zh: "解释报错",
        prompt: {
          en: "Explain the error or unusual behavior in this window. Suggest likely causes and next steps. If the interface cannot be read, explain what information is needed first.",
          zh: "请解释这个窗口中的报错或异常，给出可能原因和下一步排查建议；若无法读取界面，请先说明需要哪些信息。",
        },
      },
      {
        key: "window-guide",
        en: "How to use",
        zh: "操作指引",
        prompt: {
          en: "Explain the main areas and common controls in this software’s current interface. If the interface cannot be read, explain what information is needed first.",
          zh: "请说明这个软件当前界面主要区域的用途和常用操作入口；若无法读取界面，请先说明需要哪些信息。",
        },
      },
    ],
  };
  const iconPaths = {
    pointer:
      "M8 3.5H5.5a2 2 0 0 0-2 2V8m12.5-4.5h2.5a2 2 0 0 1 2 2V8M3.5 16v2.5a2 2 0 0 0 2 2H8m12.5-4.5v2.5a2 2 0 0 1-2 2H16M8.8 7.3l8.9 7.1-4.2.6-1.9 4z",
    folder:
      "M3 8V5a1 1 0 0 1 1-1h5l2 3h9a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V8zm0 1h18",
    file: "M14 3H5v18h14V8zm0 0v5h5M8 13h8m-8 4h5",
    window:
      "M5 4h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zM3 9h18M7 6.5h.01m3 0h.01",
    arrow: "M4 12h16m-6-6 6 6-6 6",
    download: "M12 3v13m-5-5 5 5 5-5M4 18v3h16v-3",
    close: "m6 6 12 12M6 18 18 6",
    chat: "M4 4h16v12H9l-5 4zm4 5h8m-8 3h5",
    tasks: "M8 6h12M8 12h12M8 18h12M3 6h.1M3 12h.1M3 18h.1",
    shield: "M12 3 3 6c0 7 3 12 9 15 6-3 9-8 9-15z",
    copy: "M8 8h12v13H8zM16 8V3H3v13h5",
    "up-right": "M6 18 18 6M7 6h11v11",
  };
  function drawIcon(element, name) {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("class", "icon");
    svg.setAttribute("aria-hidden", "true");
    const path = document.createElementNS(ns, "path");
    path.setAttribute("d", iconPaths[name] || iconPaths.pointer);
    svg.append(path);
    element.replaceChildren(svg);
  }
  $$("[data-icon]").forEach((element) =>
    drawIcon(element, element.dataset.icon),
  );

  const preferredLanguage = () => {
    const preferred = (navigator.languages || [navigator.language]).find(
      (value) => /^(en|zh)(-|$)/i.test(value || ""),
    );
    return (preferred || "en").toLowerCase().startsWith("zh") ? "zh" : "en";
  };
  let language = "en";
  try {
    const saved = localStorage.getItem("codex-pointer:language");
    language = saved === "en" || saved === "zh" ? saved : preferredLanguage();
  } catch {
    language = preferredLanguage();
  }
  let demoKind = "folder";
  let demoFile = "sources";
  let chatMode = "new";
  let automaticDraft = true;
  let currentDemoStatus = "demoNote";
  let currentShortcutStatus = "shortcutsNote";
  const t = (key) => copy[language][key] || copy.en[key] || key;
  function setDemoStatus(key) {
    currentDemoStatus = key;
    $("#demo-status").textContent = t(key);
  }
  function setShortcutStatus(key) {
    currentShortcutStatus = key;
    $("#shortcut-status").textContent = t(key);
  }
  function renderShortcuts() {
    const container = $("#shortcut-buttons");
    container.replaceChildren();
    taskSets[$("#feature-context").value].forEach((task) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = task[language];
      button.dataset.taskKey = task.key;
      button.title = task.prompt[language];
      button.addEventListener("click", () => {
        const field = $("#shortcut-task");
        if (
          Object.values(task.prompt).some((prompt) =>
            field.value.includes(prompt),
          )
        ) {
          setShortcutStatus("shortcutDuplicate");
          return;
        }
        const before = field.value;
        const separator =
          !before.trim() || before.endsWith("\n\n")
            ? ""
            : before.endsWith("\n")
              ? "\n"
              : "\n\n";
        const selectionStart = field.selectionStart,
          selectionEnd = field.selectionEnd;
        field.value = before + separator + task.prompt[language];
        field.setSelectionRange(selectionStart, selectionEnd);
        setShortcutStatus("shortcutAdded");
      });
      container.append(button);
    });
  }
  function updateDemoTarget() {
    const isWindow = demoKind === "window";
    const files = {
      brief: {
        name: "Brief.md",
        path: "D:/Projects/Research/Brief.md",
        icon: "file",
      },
      sources: {
        name: "Sources",
        path: "D:/Projects/Research/Sources",
        icon: "folder",
      },
      notes: {
        name: "Notes",
        path: "D:/Projects/Research/Notes",
        icon: "folder",
      },
    };
    const target = isWindow
      ? { name: t("buildOutput"), path: "Terminal · Research", icon: "window" }
      : files[demoFile];
    $("#demo-target-name").textContent = target.name;
    $("#demo-target-path").textContent = target.path;
    $("#demo-target-path").title = target.path;
    drawIcon($("#demo-target-icon"), target.icon);
    $("#folder-content").hidden = isWindow;
    $("#window-content").hidden = !isWindow;
    $$("[data-demo-kind]").forEach((tab) => {
      const selected = tab.dataset.demoKind === demoKind;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
    });
    $("#demo-desktop").setAttribute(
      "aria-labelledby",
      isWindow ? "window-tab" : "folder-tab",
    );
    $$("[data-demo-file]").forEach((row) => {
      const selected = row.dataset.demoFile === demoFile;
      row.classList.toggle("is-selected", selected);
      row.setAttribute("aria-pressed", String(selected));
    });
    if (automaticDraft)
      $("#demo-task").value = t(
        isWindow
          ? "draftWindow"
          : demoFile === "brief"
            ? "draftFile"
            : "draftFolder",
      );
  }
  function setLanguage(value, save = false) {
    language = value;
    document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
    $$("[data-i18n]").forEach((element) => {
      element.textContent = t(element.dataset.i18n);
    });
    $$("[data-i18n-placeholder]").forEach((element) => {
      element.placeholder = t(element.dataset.i18nPlaceholder);
    });
    $$("[data-i18n-aria]").forEach((element) => {
      element.setAttribute("aria-label", t(element.dataset.i18nAria));
    });
    $$("[data-language]").forEach((button) =>
      button.setAttribute(
        "aria-pressed",
        String(button.dataset.language === language),
      ),
    );
    document.title =
      language === "zh"
        ? "Codex Pointer — 指向眼前，就能开始对话。"
        : "Codex Pointer — Point at it. Bring it to Codex.";
    $('meta[name="description"]').content = t("metaDescription");
    $('meta[property="og:title"]').content = document.title;
    $('meta[property="og:description"]').content = t("metaDescription");
    updateDemoTarget();
    updateChatMode();
    renderShortcuts();
    setDemoStatus(currentDemoStatus);
    setShortcutStatus(currentShortcutStatus);
    if (save) {
      try {
        localStorage.setItem("codex-pointer:language", value);
      } catch {
        /* Site remains usable without storage. */
      }
    }
  }
  $$("[data-language]").forEach((button) =>
    button.addEventListener("click", () =>
      setLanguage(button.dataset.language, true),
    ),
  );
  function showPanel(visible) {
    $("#demo-panel").hidden = !visible;
    $("#demo-pointer").setAttribute("aria-expanded", String(visible));
  }
  $$("[data-demo-kind]").forEach((tab) => {
    tab.addEventListener("click", () => {
      demoKind = tab.dataset.demoKind;
      updateDemoTarget();
      setDemoStatus("targetSelected");
      showPanel(false);
    });
    tab.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key))
        return;
      event.preventDefault();
      const next =
        event.key === "Home"
          ? "folder"
          : event.key === "End"
            ? "window"
            : demoKind === "folder"
              ? "window"
              : "folder";
      const target = $('[data-demo-kind="' + next + '"]');
      target.click();
      target.focus();
    });
  });
  $$("[data-demo-file]").forEach((row) =>
    row.addEventListener("click", () => {
      demoFile = row.dataset.demoFile;
      updateDemoTarget();
      showPanel(false);
      setDemoStatus("targetSelected");
    }),
  );
  $("#demo-pointer").addEventListener("click", () =>
    showPanel($("#demo-panel").hidden),
  );
  $("#open-panel").addEventListener("click", () => showPanel(true));
  $("#close-panel").addEventListener("click", () => {
    showPanel(false);
    $("#demo-pointer").focus();
  });
  $("#select-target").addEventListener("click", () => {
    demoKind = demoKind === "folder" ? "window" : "folder";
    updateDemoTarget();
    showPanel(false);
    setDemoStatus("targetSelected");
  });
  function updateChatMode() {
    $$("[data-chat]").forEach((tab) => {
      const active = tab.dataset.chat === chatMode;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-pressed", String(active));
    });
    $("#linked-chat").hidden = chatMode !== "continue";
    const label = $("#demo-continue [data-i18n]");
    label.dataset.i18n = chatMode === "new" ? "continueInCodex" : "sendToChat";
    label.textContent = t(label.dataset.i18n);
  }
  $$("[data-chat]").forEach((button) =>
    button.addEventListener("click", () => {
      chatMode = button.dataset.chat;
      updateChatMode();
      setDemoStatus("demoNote");
    }),
  );
  $("#demo-task").addEventListener("input", () => {
    automaticDraft = false;
  });
  $("#demo-continue").addEventListener("click", () =>
    setDemoStatus(chatMode === "new" ? "demoContinue" : "demoExisting"),
  );
  $("#demo-screenshot").addEventListener("change", () =>
    setDemoStatus("screenshotNote"),
  );
  $(".demo-canvas").addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("#demo-panel").hidden) {
      event.preventDefault();
      showPanel(false);
      $("#demo-pointer").focus();
    }
  });
  $("#feature-context").addEventListener("change", () => {
    renderShortcuts();
    setShortcutStatus("contextChanged");
  });
  $("#clear-task").addEventListener("click", () => {
    $("#shortcut-task").value = "";
    setShortcutStatus("shortcutsNote");
    $("#shortcut-task").focus();
  });
  $("#try-file").addEventListener("click", () => {
    $("#feature-context").value = "file";
    renderShortcuts();
    setShortcutStatus("contextChanged");
  });
  document.addEventListener("dragover", (event) => event.preventDefault());
  document.addEventListener("drop", (event) => {
    event.preventDefault();
    setDemoStatus("dropNote");
    setShortcutStatus("dropNote");
  });
  $("#copy-commands").addEventListener("click", async () => {
    const text = $("#install-commands").textContent;
    try {
      if (!navigator.clipboard || !navigator.clipboard.writeText)
        throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(text);
      $("#copy-status").textContent = t("copied");
    } catch {
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents($("#install-commands"));
      selection.removeAllRanges();
      selection.addRange(range);
      $("#copy-status").textContent = t("copyFallback");
    }
  });

  const config = window.POINTER_SITE_CONFIG || {};
  const valid = (value) =>
    typeof value === "string" && /^[A-Za-z0-9_.-]+$/.test(value);
  if (
    valid(config.owner) &&
    valid(config.repository) &&
    valid(config.version) &&
    valid(config.windowsAsset)
  ) {
    const repository =
      "https://github.com/" + config.owner + "/" + config.repository;
    const release =
      repository + "/releases/tag/v" + encodeURIComponent(config.version);
    const links = {
      repository,
      release,
      download:
        repository +
        "/releases/download/v" +
        encodeURIComponent(config.version) +
        "/" +
        encodeURIComponent(config.windowsAsset),
      license: repository + "/blob/main/LICENSE",
    };
    $$("[data-link]").forEach((link) => {
      link.href = links[link.dataset.link];
      link.target = "_blank";
      link.rel = "noopener noreferrer";
    });
    $$("[data-version]").forEach((element) => {
      element.textContent = "v" + config.version;
    });
  }
  setLanguage(language);
})();
