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

  const toast = document.getElementById("toast");
  const loader = document.getElementById("loader");
  const loaderText = document.getElementById("loader-text");

  let toastTimer = null;

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
      headers: { "Content-Type": "application/json" },
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
  function renderRecommendations(recs) {
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
        '<p class="rec-why">' + escapeHTML(rec.why) + "</p>";
      recommendationsEl.appendChild(card);
      // Animate the bar after insertion.
      requestAnimationFrame(() => {
        card.querySelector(".bar > span").style.width = rec.match + "%";
      });
    });
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
    renderRecommendations(data.recommendations);
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
    showLoader("Analyzing your profile…");
    try {
      const data = await postJSON("/api/start", form);
      intro.classList.add("hidden");
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
      const data = await postJSON("/api/chat", { answer: answer });
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
    workspace.classList.add("hidden");
    intro.classList.remove("hidden");
    chatEl.innerHTML = "";
    recommendationsEl.innerHTML = "";
    traitsEl.innerHTML = "";
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  // --- Wire up ---
  profileForm.addEventListener("submit", handleStart);
  chatForm.addEventListener("submit", handleChat);
  restartBtn.addEventListener("click", handleRestart);
})();
