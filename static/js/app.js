/* ===== MajorMatch front-end logic ===== */
(function () {
  "use strict";

  const MAX_QUESTIONS = parseInt(document.body.dataset.maxQuestions || "6", 10);

  // --- Elements ---
  const intro = document.getElementById("intro");
  const workspace = document.getElementById("workspace");
  const profileForm = document.getElementById("profile-form");
  const startBtn = document.getElementById("start-btn");
  const restartBtn = document.getElementById("restart-btn");

  const recommendationsEl = document.getElementById("recommendations");
  const traitsEl = document.getElementById("traits");
  const chatEl = document.getElementById("chat");
  const chatForm = document.getElementById("chat-form");
  const chatInput = document.getElementById("chat-input");
  const sendBtn = document.getElementById("send-btn");
  const progressEl = document.getElementById("progress");
  const doneNote = document.getElementById("done-note");

  const historyEl = document.getElementById("history");
  const historyList = document.getElementById("history-list");
  const historyHide = document.getElementById("history-hide");

  const toast = document.getElementById("toast");
  const loader = document.getElementById("loader");
  const loaderText = document.getElementById("loader-text");

  // Auth elements
  const authEmail = document.getElementById("auth-email");
  const loginBtn = document.getElementById("login-btn");
  const signupBtn = document.getElementById("signup-btn");
  const logoutBtn = document.getElementById("logout-btn");
  const authModal = document.getElementById("auth-modal");
  const authClose = document.getElementById("auth-close");
  const authForm = document.getElementById("auth-form");
  const authTitle = document.getElementById("auth-title");
  const authSub = document.getElementById("auth-sub");
  const authSubmit = document.getElementById("auth-submit");
  const authError = document.getElementById("auth-error");
  const authSwitchText = document.getElementById("auth-switch-text");
  const authSwitchBtn = document.getElementById("auth-switch-btn");
  const authEmailInput = document.getElementById("auth-email-input");
  const authPasswordInput = document.getElementById("auth-password-input");

  let toastTimer = null;
  // Public id of the session currently on screen; used to attach feedback.
  let currentSessionId = null;
  // CSRF token (double-submit): read from the page, refreshed from /auth/me.
  const metaCsrf = document.querySelector('meta[name="csrf-token"]');
  let csrfToken = metaCsrf ? metaCsrf.getAttribute("content") : "";
  let authMode = "login"; // or "register"

  // --- Helpers ---
  function showLoader(text) {
    loaderText.textContent = text || "Thinking…";
    loader.classList.remove("hidden");
  }
  function hideLoader() {
    loader.classList.add("hidden");
  }
  function showToast(message) {
    toast.textContent = message;
    toast.classList.remove("hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.add("hidden"), 4500);
  }

  async function postJSON(url, body) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.error || "Something went wrong. Please try again.");
    }
    return data;
  }

  function escapeHTML(str) {
    const div = document.createElement("div");
    div.textContent = str == null ? "" : String(str);
    return div.innerHTML;
  }

  // --- Rendering ---
  function buildFeedback(major) {
    const wrap = document.createElement("div");
    wrap.className = "rec-feedback";
    wrap.dataset.major = major;

    const q = document.createElement("span");
    q.className = "fb-q";
    q.textContent = "Was this major helpful?";

    const up = document.createElement("button");
    up.type = "button";
    up.className = "fb-btn";
    up.dataset.helpful = "1";
    up.setAttribute("aria-label", "Helpful");
    up.textContent = "👍";

    const down = document.createElement("button");
    down.type = "button";
    down.className = "fb-btn";
    down.dataset.helpful = "0";
    down.setAttribute("aria-label", "Not helpful");
    down.textContent = "👎";

    wrap.append(q, up, down);
    return wrap;
  }

  function dataHTML(rec) {
    const d = rec.data;
    if (!d) return "";
    if (!d.grounded) {
      return '<p class="rec-data ungrounded" title="Not found in the reference dataset">' +
        "📊 Not in our reference dataset</p>";
    }
    const parts = [];
    if (d.median_earnings != null) {
      parts.push("$" + Number(d.median_earnings).toLocaleString() + " median");
    }
    if (d.employment_rate != null) {
      parts.push(Math.round(d.employment_rate * 100) + "% employed");
    }
    if (!parts.length) return "";
    return '<p class="rec-data" title="Real labour-market data — U.S. Census ACS">📊 ' +
      escapeHTML(parts.join(" · ")) + "</p>";
  }

  function renderRecommendations(recs, showFeedback) {
    recommendationsEl.innerHTML = "";
    (recs || []).forEach((rec, i) => {
      const card = document.createElement("div");
      card.className = "rec-card" + (i === 0 ? " top" : "");
      card.style.animationDelay = i * 60 + "ms";
      card.innerHTML =
        '<div class="rec-top-row">' +
          '<span class="rec-name">' + escapeHTML(rec.name) +
            (i === 0 ? ' <span class="rec-badge">Best fit</span>' : "") +
          "</span>" +
          '<span class="rec-match">' + rec.match + "%</span>" +
        "</div>" +
        '<div class="bar"><span></span></div>' +
        '<p class="rec-why">' + escapeHTML(rec.why) + "</p>" +
        dataHTML(rec);
      recommendationsEl.appendChild(card);
      if (showFeedback) {
        card.appendChild(buildFeedback(rec.name));
      }
      // Animate the bar after insertion.
      requestAnimationFrame(() => {
        card.querySelector(".bar > span").style.width = rec.match + "%";
      });
    });
  }

  async function handleFeedbackClick(event) {
    const btn = event.target.closest(".fb-btn");
    if (!btn || !recommendationsEl.contains(btn)) return;
    const wrap = btn.closest(".rec-feedback");
    if (!wrap || wrap.classList.contains("answered") || !currentSessionId) return;

    const major = wrap.dataset.major || "";
    const helpful = btn.dataset.helpful === "1";
    wrap.classList.add("answered");
    try {
      await postJSON("/api/v1/feedback", {
        session_id: currentSessionId,
        major: major,
        helpful: helpful,
      });
      wrap.textContent = helpful
        ? "🎉 Thanks — glad it helped!"
        : "🙏 Thanks — we'll keep improving.";
    } catch (err) {
      wrap.classList.remove("answered");
      showToast(err.message);
    }
  }

  function renderTraits(scores) {
    traitsEl.innerHTML = "";
    Object.keys(scores || {}).forEach((trait) => {
      const value = scores[trait];
      const row = document.createElement("div");
      row.className = "trait-row";
      row.innerHTML =
        '<div class="trait-label"><span>' + escapeHTML(trait) +
          "</span><span>" + value + "%</span></div>" +
        '<div class="trait-bar"><span></span></div>';
      traitsEl.appendChild(row);
      requestAnimationFrame(() => {
        row.querySelector(".trait-bar > span").style.width = value + "%";
      });
    });
  }

  function addBubble(text, who) {
    const bubble = document.createElement("div");
    bubble.className = "bubble " + who;
    bubble.textContent = text;
    chatEl.appendChild(bubble);
    chatEl.scrollTop = chatEl.scrollHeight;
    return bubble;
  }

  function updateProgress(asked) {
    const shown = Math.min(asked, MAX_QUESTIONS);
    progressEl.textContent = "Question " + shown + " of ~" + MAX_QUESTIONS;
  }

  function applyResult(data) {
    if (data.session_id) currentSessionId = data.session_id;
    const showFeedback = !!(data.done && currentSessionId);
    renderRecommendations(data.recommendations, showFeedback);
    renderTraits(data.scores);

    if (data.message) addBubble(data.message, "advisor");

    if (data.done || !data.question) {
      addBubble(
        "That's everything I need — your final matches are on the left. 🎉",
        "advisor"
      );
      chatForm.classList.add("hidden");
      doneNote.classList.remove("hidden");
      progressEl.textContent = "Complete";
    } else {
      addBubble(data.question, "advisor");
      updateProgress(data.questions_asked);
      chatInput.focus();
    }
  }

  // --- Flow ---
  async function handleStart(event) {
    event.preventDefault();
    const interests = document.getElementById("interests").value.trim();
    const hobbies = document.getElementById("hobbies").value.trim();
    if (!interests && !hobbies) {
      showToast("Tell us at least your interests or hobbies to get started.");
      return;
    }

    const form = {
      interests: interests,
      hobbies: hobbies,
      subjects: document.getElementById("subjects").value.trim(),
      strengths: document.getElementById("strengths").value.trim(),
      work_style: document.getElementById("work_style").value,
      goals: document.getElementById("goals").value.trim(),
      dislikes: document.getElementById("dislikes").value.trim(),
    };

    startBtn.disabled = true;
    currentSessionId = null;
    showLoader("Analyzing your profile…");
    try {
      const data = await postJSON("/api/v1/start", form);
      intro.classList.add("hidden");
      historyEl.classList.add("hidden");
      workspace.classList.remove("hidden");
      chatForm.classList.remove("hidden");
      doneNote.classList.add("hidden");
      chatEl.innerHTML = "";
      applyResult(data);
    } catch (err) {
      showToast(err.message);
    } finally {
      hideLoader();
      startBtn.disabled = false;
    }
  }

  async function handleChat(event) {
    event.preventDefault();
    const answer = chatInput.value.trim();
    if (!answer) return;

    addBubble(answer, "student");
    chatInput.value = "";
    sendBtn.disabled = true;
    chatInput.disabled = true;
    const typing = addBubble("Advisor is thinking…", "advisor");
    typing.classList.add("typing");

    try {
      const data = await postJSON("/api/v1/chat", { answer: answer });
      typing.remove();
      applyResult(data);
    } catch (err) {
      typing.remove();
      showToast(err.message);
    } finally {
      sendBtn.disabled = false;
      chatInput.disabled = false;
    }
  }

  function handleRestart() {
    currentSessionId = null;
    workspace.classList.add("hidden");
    intro.classList.remove("hidden");
    chatForm.classList.remove("hidden");
    doneNote.classList.add("hidden");
    progressEl.textContent = "";
    chatEl.innerHTML = "";
    recommendationsEl.innerHTML = "";
    traitsEl.innerHTML = "";
    loadHistory();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  // --- Past sessions (history) ---
  function formatWhen(iso) {
    if (!iso) return "";
    // Stored timestamps are UTC; tag them so local display is correct.
    if (!/(Z|[+-]\d\d:?\d\d)$/.test(iso)) iso += "Z";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    return (
      d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) +
      ", " +
      d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
    );
  }

  function renderHistory(sessions) {
    historyList.innerHTML = "";
    if (!sessions || !sessions.length) {
      historyEl.classList.add("hidden");
      return;
    }
    sessions.forEach((s) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "history-item";

      const top = s.top_major || "Session";
      const status = s.status === "completed" ? "Final" : "In progress";
      const meta = status + (s.is_demo ? " · demo" : "") + " · " + formatWhen(s.created_at);

      item.innerHTML =
        '<span class="hi-major">' + escapeHTML(top) + "</span>" +
        (s.top_match != null ? '<span class="hi-match">' + s.top_match + "%</span>" : "") +
        '<span class="hi-meta">' + escapeHTML(meta) + "</span>";
      item.addEventListener("click", () => viewSession(s));
      historyList.appendChild(item);
    });
    historyEl.classList.remove("hidden");
  }

  async function loadHistory() {
    try {
      const res = await fetch("/api/v1/history", { headers: { Accept: "application/json" } });
      if (!res.ok) return;
      const data = await res.json();
      renderHistory(data.sessions);
    } catch (err) {
      /* History is a nicety; ignore failures silently. */
    }
  }

  function viewSession(s) {
    currentSessionId = s.session_id || null;
    const completed = s.status === "completed";

    historyEl.classList.add("hidden");
    intro.classList.add("hidden");
    workspace.classList.remove("hidden");
    chatEl.innerHTML = "";

    renderRecommendations(s.recommendations, completed && !!currentSessionId);
    renderTraits(s.scores);
    if (s.message) addBubble(s.message, "advisor");
    addBubble(
      "You're viewing a saved session from " + formatWhen(s.created_at) +
        ". Start over anytime to explore again.",
      "advisor"
    );

    chatForm.classList.add("hidden");
    doneNote.classList.remove("hidden");
    progressEl.textContent = completed ? "Complete" : "Saved";
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  // --- Auth ---
  function renderAuth(state) {
    const authed = state && state.authenticated;
    if (state && state.csrf_token) csrfToken = state.csrf_token;
    if (authed) {
      authEmail.textContent = state.email;
      authEmail.classList.remove("hidden");
      logoutBtn.classList.remove("hidden");
      loginBtn.classList.add("hidden");
      signupBtn.classList.add("hidden");
    } else {
      authEmail.classList.add("hidden");
      logoutBtn.classList.add("hidden");
      loginBtn.classList.remove("hidden");
      signupBtn.classList.remove("hidden");
    }
  }

  async function loadAuth() {
    try {
      const res = await fetch("/api/v1/auth/me", { headers: { Accept: "application/json" } });
      if (res.ok) renderAuth(await res.json());
    } catch (err) {
      /* auth is a progressive enhancement; ignore failures */
    }
  }

  function setAuthMode(mode) {
    authMode = mode;
    const isRegister = mode === "register";
    authTitle.textContent = isRegister ? "Sign up" : "Log in";
    authSubmit.textContent = isRegister ? "Create account" : "Log in";
    authSub.textContent = isRegister
      ? "Create an account to save and sync your matches."
      : "Sign in to sync your matches across devices.";
    authSwitchText.textContent = isRegister ? "Already have an account?" : "New here?";
    authSwitchBtn.textContent = isRegister ? "Log in" : "Create an account";
    authPasswordInput.setAttribute(
      "autocomplete", isRegister ? "new-password" : "current-password"
    );
    authError.classList.add("hidden");
  }

  function openAuth(mode) {
    setAuthMode(mode);
    authModal.classList.remove("hidden");
    authEmailInput.focus();
  }

  function closeAuth() {
    authModal.classList.add("hidden");
    authForm.reset();
    authError.classList.add("hidden");
  }

  async function handleAuthSubmit(event) {
    event.preventDefault();
    const email = authEmailInput.value.trim();
    const password = authPasswordInput.value;
    if (!email || !password) {
      authError.textContent = "Enter your email and password.";
      authError.classList.remove("hidden");
      return;
    }
    authSubmit.disabled = true;
    const url = authMode === "register" ? "/api/v1/auth/register" : "/api/v1/auth/login";
    try {
      const data = await postJSON(url, { email: email, password: password });
      renderAuth(data);
      closeAuth();
      showToast(authMode === "register" ? "Account created — welcome!" : "Signed in.");
      loadHistory();
    } catch (err) {
      authError.textContent = err.message;
      authError.classList.remove("hidden");
    } finally {
      authSubmit.disabled = false;
    }
  }

  async function handleLogout() {
    try {
      const data = await postJSON("/api/v1/auth/logout", {});
      renderAuth(data);
      showToast("Signed out.");
      loadHistory();
    } catch (err) {
      showToast(err.message);
    }
  }

  // --- Wire up ---
  profileForm.addEventListener("submit", handleStart);
  chatForm.addEventListener("submit", handleChat);
  restartBtn.addEventListener("click", handleRestart);
  recommendationsEl.addEventListener("click", handleFeedbackClick);
  historyHide.addEventListener("click", () => historyEl.classList.add("hidden"));

  loginBtn.addEventListener("click", () => openAuth("login"));
  signupBtn.addEventListener("click", () => openAuth("register"));
  logoutBtn.addEventListener("click", handleLogout);
  authClose.addEventListener("click", closeAuth);
  authSwitchBtn.addEventListener("click", () =>
    setAuthMode(authMode === "register" ? "login" : "register")
  );
  authForm.addEventListener("submit", handleAuthSubmit);
  authModal.addEventListener("click", (e) => {
    if (e.target === authModal) closeAuth();
  });

  loadAuth();
  loadHistory();
})();
