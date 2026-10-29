/* iPAS 題庫練習 — 純前端, 無後端。題庫由 data/questions-*.js 以 window.QUESTION_BANK 提供 */
(function () {
  "use strict";

  var QUIZ_SIZE = 20;
  var STORE_KEY = "ipas-quiz-stats-v1";

  var SUBJECTS = {
    junior: [
      { id: 1, name: "人工智慧基礎概論" },
      { id: 2, name: "生成式AI應用與規劃" },
    ],
    middle: [
      { id: 1, name: "人工智慧技術應用與規劃" },
      { id: 2, name: "大數據處理分析與應用" },
      { id: 3, name: "機器學習技術與應用" },
    ],
  };

  var state = {
    level: "junior",
    subject: "all", // "all" 或科目數字
    origin: "all",  // "all" | "past"(歷屆試題) | "guide"(學習指引範例題)
    quiz: null,     // { list, optionOrders, idx, answers[], correctCount }
  };

  // ---------- 工具 ----------
  function $(id) { return document.getElementById(id); }
  function shuffle(arr) {
    var a = arr.slice();
    for (var i = a.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var t = a[i]; a[i] = a[j]; a[j] = t;
    }
    return a;
  }
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  // 選項是隨機排序的,但詳解文字裡的「(A)」指的是原始卷面字母,直接顯示會指錯選項。
  // 依本題洗牌結果改寫成畫面上的字母。只改真正的選項引用:
  // - 全形（A）一律視為引用
  // - 半形 (A) 只在前一字不是英數字時才算(避開 P(A)、np.linalg.inv(A) 這類寫法),
  //   且題幹若出現半形 (A) 代表那是程式碼填空標記,整題的半形引用都不動
  // - 裸字母只在「選項／答案／取／選／只有／僅／剩下」之後,或「X選項」之前才算引用,
  //   可帶「B、C、D」這種串列;其餘(程式碼A、類別B、999°C…)一律不動
  // - 組合題(選項本身是「B、C、F」這類字母／編號清單)裡的字母指題幹敘述,
  //   只換「對應選項X／對應答案X」
  var LIST = "([A-D](?:\\s*[、與和及,，]\\s*[A-D])*)";
  var END = "(?![A-Za-z0-9_=]|\\(\\d)";
  // 前綴、後綴合成一條,單次掃描,避免「只有B選項」被換兩次
  var RE_BARE = new RegExp(
    "(選項|答案(?:為|取|採|是)?|取|採|選|只有|僅|剩下)(\\s?)" + LIST + END +
    "|(^|[^A-Za-z0-9_])" + LIST + "(\\s?(?:兩個|三個|四個)?選項)", "g");
  var RE_COMBO_REF = /(對應(?:選項|答案))(\s?)([A-D])(?![A-Za-z0-9_])/g;
  var RE_COMBO_OPT = /^(?:[一-鿿]{0,3}[A-F]|\d)(?:\s*[、,，]\s*(?:[一-鿿]{0,3}[A-F]|\d))*$/;

  function isComboQuestion(q) {
    return Object.keys(q.options || {}).every(function (k) {
      return RE_COMBO_OPT.test(String(q.options[k]).trim());
    });
  }

  function remapLetters(text, q, order) {
    if (!text || !order) return text;
    var map = {};
    order.forEach(function (key, i) { map[key] = "ABCD"[i]; });
    var mapList = function (s) { return s.replace(/[A-D]/g, function (L) { return map[L] || L; }); };
    var codeBlanks = /\([A-D]\)/.test(q.stem || "");
    var out = String(text)
      .replace(/（([A-D])）/g, function (m, L) {
        return map[L] ? "（" + map[L] + "）" : m;
      })
      .replace(/([^A-Za-z0-9_]|^)\(([A-D])\)/g, function (m, pre, L) {
        return codeBlanks || !map[L] ? m : pre + "(" + map[L] + ")";
      });
    if (isComboQuestion(q)) {
      return out.replace(RE_COMBO_REF, function (m, pre, sp, L) { return pre + sp + (map[L] || L); });
    }
    return out.replace(RE_BARE, function (m, pre, sp, list, lead, list2, tail) {
      return pre !== undefined ? pre + sp + mapList(list) : lead + mapList(list2) + tail;
    });
  }

  function show(viewId) {
    ["view-setup", "view-quiz", "view-result", "view-stats"].forEach(function (v) {
      $(v).classList.toggle("hidden", v !== viewId);
    });
    $("nav-home").classList.toggle("active", viewId !== "view-stats");
    $("nav-stats").classList.toggle("active", viewId === "view-stats");
  }
  function figHtml(src) {
    return '<img class="q-fig" src="' + esc(src) + '" alt="題目附圖">';
  }
  function srcLabel(q) {
    if (q.origin === "guide") return "學習指引 範例題";
    return q.session + " 梯次 原卷第 " + q.number + " 題";
  }

  // ---------- 統計儲存 ----------
  function showConfirm(msg, onOk) {
    var modal = $("modal");
    var opener = document.activeElement;
    $("modal-msg").textContent = msg;
    modal.classList.remove("hidden");
    $("modal-ok").focus();

    function close(restoreFocus) {
      modal.classList.add("hidden");
      document.removeEventListener("keydown", onKey, true);
      if (restoreFocus !== false && opener && opener.focus) opener.focus();
    }
    function onKey(e) {
      if (e.key === "Escape") { e.preventDefault(); close(); return; }
      if (e.key !== "Tab") return;
      // 焦點鎖在對話框內的兩顆按鈕之間
      var f = [$("modal-ok"), $("modal-cancel")];
      var i = f.indexOf(document.activeElement);
      e.preventDefault();
      f[(i + (e.shiftKey ? f.length - 1 : 1) + f.length) % f.length].focus();
    }
    document.addEventListener("keydown", onKey, true);

    // 確定後畫面會切換, 原開啟按鈕多半已隱藏, 故不還原焦點, 改由 onOk 決定落點
    $("modal-ok").onclick = function () { close(false); onOk(); };
    $("modal-cancel").onclick = function () { close(); };
    modal.onclick = function (e) { if (e.target === modal) close(); };
  }

  function loadStats() {
    try { return JSON.parse(localStorage.getItem(STORE_KEY)) || { attempts: [] }; }
    catch (e) { return { attempts: [] }; }
  }
  function saveAttempt(attempt) {
    var s = loadStats();
    s.attempts.push(attempt);
    localStorage.setItem(STORE_KEY, JSON.stringify(s));
  }

  // ---------- 設定畫面 ----------
  function pool() {
    var qs = window.QUESTION_BANK[state.level] || [];
    return qs.filter(function (q) {
      if (state.subject !== "all" && q.subject !== state.subject) return false;
      if (state.origin !== "all" && (q.origin || "past") !== state.origin) return false;
      return true;
    });
  }

  function renderSetup() {
    var seg = $("subject-seg");
    var subjects = SUBJECTS[state.level];
    var html = '<button data-subject="all" class="seg-btn' + (state.subject === "all" ? " active" : "") + '">全部科目混合</button>';
    subjects.forEach(function (s) {
      html += '<button data-subject="' + s.id + '" class="seg-btn' + (state.subject === s.id ? " active" : "") + '">科目' + s.id + " " + esc(s.name) + "</button>";
    });
    seg.innerHTML = html;
    Array.prototype.forEach.call(seg.querySelectorAll("button"), function (b) {
      b.onclick = function () {
        var v = b.getAttribute("data-subject");
        state.subject = v === "all" ? "all" : parseInt(v, 10);
        renderSetup();
      };
    });
    Array.prototype.forEach.call(document.querySelectorAll("#origin-seg .seg-btn"), function (b) {
      b.classList.toggle("active", b.getAttribute("data-origin") === state.origin);
      b.onclick = function () {
        state.origin = b.getAttribute("data-origin");
        renderSetup();
      };
    });
    var p = pool();
    var guideN = p.filter(function (q) { return q.origin === "guide"; }).length;
    var txt = "題庫共 " + p.length + " 題,每次隨機抽 " + QUIZ_SIZE + " 題";
    if (state.origin === "all" && guideN) {
      txt += "(歷屆 " + (p.length - guideN) + " 題、學習指引 " + guideN + " 題)";
    }
    $("pool-info").textContent = txt + "。";
  }

  // ---------- 出題 ----------
  function startQuiz() {
    var p = pool();
    if (p.length < QUIZ_SIZE) { alert("題庫不足 " + QUIZ_SIZE + " 題"); return; }
    var list = shuffle(p).slice(0, QUIZ_SIZE);
    state.quiz = {
      list: list,
      optionOrders: list.map(function (q) { return shuffle(Object.keys(q.options)); }),
      idx: 0,
      answers: [],
      correctCount: 0,
    };
    show("view-quiz");
    renderQuestion();
  }

  function renderQuestion() {
    var quiz = state.quiz;
    var q = quiz.list[quiz.idx];
    var order = quiz.optionOrders[quiz.idx];

    $("progress-bar").style.width = (quiz.idx / QUIZ_SIZE * 100) + "%";
    $("quiz-pos").textContent = "第 " + (quiz.idx + 1) + " / " + QUIZ_SIZE + " 題";
    $("quiz-score").textContent = "答對 " + quiz.correctCount + " 題";
    $("btn-next").classList.add("hidden");

    var html = '<div class="q-tags">'
      + '<span class="tag">' + esc(q.subject_name) + "</span>"
      + '<span class="tag src">' + esc(srcLabel(q)) + "</span>"
      + "</div>";

    if (q.context) {
      html += '<div class="q-context"><span class="ctx-label">題組情境</span>' + esc(q.context.text);
      (q.context.figures || []).forEach(function (src) { html += figHtml(src); });
      html += "</div>";
    }

    html += '<div class="q-stem">' + esc(q.stem) + "</div>";
    (q.figures || []).forEach(function (f) {
      if (f.position === "stem") html += figHtml(f.src);
    });

    order.forEach(function (key, i) {
      var displayLetter = "ABCD"[i];
      var optFigs = (q.figures || []).filter(function (f) { return f.position === "option:" + key; });
      html += '<button class="opt" data-key="' + key + '">'
        + '<span class="opt-letter">' + displayLetter + "</span>"
        + '<span class="opt-body">' + esc(q.options[key]);
      optFigs.forEach(function (f) { html += figHtml(f.src); });
      html += '<span class="opt-note hidden"></span></span></button>';
    });

    (q.figures || []).forEach(function (f) {
      if (f.position === "end") html += figHtml(f.src);
    });

    html += '<div id="answer-area"></div>';
    $("question-card").innerHTML = html;

    Array.prototype.forEach.call($("question-card").querySelectorAll(".opt"), function (b) {
      b.onclick = function () { answer(b.getAttribute("data-key")); };
    });
  }

  function answer(chosenKey) {
    var quiz = state.quiz;
    var q = quiz.list[quiz.idx];
    if (quiz.answers.length > quiz.idx) return; // 已作答

    var order = quiz.optionOrders[quiz.idx];
    var correct = chosenKey === q.answer;
    if (correct) quiz.correctCount++;
    quiz.answers.push({ id: q.id, chosen: chosenKey, correct: correct, subject: q.subject });

    var card = $("question-card");
    Array.prototype.forEach.call(card.querySelectorAll(".opt"), function (b) {
      b.disabled = true;
      var key = b.getAttribute("data-key");
      if (key === q.answer) b.classList.add("correct");
      else if (key === chosenKey) b.classList.add("wrong");
      // 每個選項掛上註解
      var note = b.querySelector(".opt-note");
      if (q.explanation && q.explanation.options && q.explanation.options[key]) {
        note.textContent = remapLetters(q.explanation.options[key], q, order);
        note.classList.remove("hidden");
      }
    });

    var area = $("answer-area");
    var html = '<div class="verdict ' + (correct ? "ok" : "no") + '">'
      + (correct ? "○ 答對!" : "✗ 答錯了,記下來——")
      + "</div>";
    if (q.explanation && q.explanation.approach) {
      html += '<div class="explain"><h3>解題思路'
            + (q.explanation.source === "official" ? '<span class="badge-official">官方解析</span>' : "")
            + "</h3>" + esc(remapLetters(q.explanation.approach, q, order));
          if (q.explanation.errata) html += '<div class="note">📌 官方勘誤:' + esc(remapLetters(q.explanation.errata, q, order)) + "</div>";
      if (q.explanation.note) html += '<div class="note">⚠ 答案疑義:' + esc(remapLetters(q.explanation.note, q, order)) + "</div>";
      if (q.explanation.timeliness) html += '<div class="note timely">⏳ 時效提醒:' + esc(remapLetters(q.explanation.timeliness, q, order)) + "</div>";
      html += "</div>";
    } else {
      html += '<div class="explain pending">此題 AI 詳解尚未生成。</div>';
    }
    area.innerHTML = html;

    $("quiz-score").textContent = "答對 " + quiz.correctCount + " 題";
    $("btn-next").textContent = quiz.idx === QUIZ_SIZE - 1 ? "看成績" : "下一題";
    $("btn-next").classList.remove("hidden");
  }

  function next() {
    var quiz = state.quiz;
    if (quiz.answers.length <= quiz.idx) return;
    if (quiz.idx === QUIZ_SIZE - 1) { finish(); return; }
    quiz.idx++;
    renderQuestion();
    window.scrollTo(0, 0);
  }

  // ---------- 結果 ----------
  function finish() {
    var quiz = state.quiz;
    $("progress-bar").style.width = "100%";

    var bySubject = {};
    quiz.answers.forEach(function (a) {
      var s = bySubject[a.subject] || (bySubject[a.subject] = { total: 0, correct: 0 });
      s.total++;
      if (a.correct) s.correct++;
    });

    saveAttempt({
      time: Date.now(),
      level: state.level,
      subject: state.subject,
      total: QUIZ_SIZE,
      correct: quiz.correctCount,
      answers: quiz.answers,
    });

    var pct = Math.round(quiz.correctCount / QUIZ_SIZE * 100);
    $("result-title").textContent = (state.level === "junior" ? "初級" : "中級") + "練習完成";
    $("result-score").textContent = quiz.correctCount + " / " + QUIZ_SIZE;

    var subjectNames = {};
    SUBJECTS[state.level].forEach(function (s) { subjectNames[s.id] = s.name; });
    var bd = "正確率 " + pct + "%";
    var keys = Object.keys(bySubject);
    if (keys.length > 1) {
      bd += "<table><tr><th>科目</th><th>答對</th></tr>";
      keys.sort().forEach(function (k) {
        var s = bySubject[k];
        bd += "<tr><td>科目" + k + " " + esc(subjectNames[k] || "") + "</td><td>" + s.correct + " / " + s.total + "</td></tr>";
      });
      bd += "</table>";
    }
    $("result-breakdown").innerHTML = bd;
    $("review-list").classList.add("hidden");
    $("review-list").innerHTML = "";
    show("view-result");
    window.scrollTo(0, 0);
  }

  function renderReview() {
    var quiz = state.quiz;
    var wrongs = quiz.answers
      .map(function (a, i) { return { a: a, q: quiz.list[i], order: quiz.optionOrders[i] }; })
      .filter(function (x) { return !x.a.correct; });
    var box = $("review-list");
    if (!wrongs.length) {
      box.innerHTML = '<div class="card">全對,沒有錯題 🎉</div>';
    } else {
      box.innerHTML = wrongs.map(function (x) {
        var q = x.q;
        var order = x.order;
        var html = '<div class="card review-q"><div class="q-tags">'
          + '<span class="tag">' + esc(q.subject_name) + "</span>"
          + '<span class="tag src">' + esc(srcLabel(q)) + "</span></div>";
        if (q.context) html += '<div class="q-context">' + esc(q.context.text) + "</div>";
        html += '<div class="q-stem">' + esc(q.stem) + "</div>";
        (q.figures || []).forEach(function (f) { if (f.position === "stem") html += figHtml(f.src); });
        x.order.forEach(function (key, i) {
          var cls = key === q.answer ? " correct" : (key === x.a.chosen ? " wrong" : "");
          var optFigs = (q.figures || []).filter(function (f) { return f.position === "option:" + key; });
          html += '<div class="opt' + cls + '"><span class="opt-letter">' + "ABCD"[i] + "</span>"
            + '<span class="opt-body">' + esc(q.options[key]);
          optFigs.forEach(function (f) { html += figHtml(f.src); });
          if (q.explanation && q.explanation.options && q.explanation.options[key]) {
            html += '<span class="opt-note">' + esc(remapLetters(q.explanation.options[key], q, order)) + "</span>";
          }
          html += "</span></div>";
        });
        if (q.explanation && q.explanation.approach) {
          html += '<div class="explain"><h3>解題思路'
            + (q.explanation.source === "official" ? '<span class="badge-official">官方解析</span>' : "")
            + "</h3>" + esc(remapLetters(q.explanation.approach, q, order));
          if (q.explanation.errata) html += '<div class="note">📌 官方勘誤:' + esc(remapLetters(q.explanation.errata, q, order)) + "</div>";
          if (q.explanation.note) html += '<div class="note">⚠ 答案疑義:' + esc(remapLetters(q.explanation.note, q, order)) + "</div>";
          if (q.explanation.timeliness) html += '<div class="note timely">⏳ 時效提醒:' + esc(remapLetters(q.explanation.timeliness, q, order)) + "</div>";
          html += "</div>";
        }
        return html + "</div>";
      }).join("");
    }
    box.classList.remove("hidden");
  }

  // ---------- 統計 ----------
  function renderStats() {
    var s = loadStats();
    var box = $("stats-content");
    if (!s.attempts.length) {
      box.innerHTML = '<p class="muted">還沒有作答紀錄,先去刷一輪吧。</p>';
      show("view-stats");
      return;
    }
    var levelNames = { junior: "初級", middle: "中級" };
    // 各級別/科目累計正確率
    var agg = {};
    s.attempts.forEach(function (at) {
      (at.answers || []).forEach(function (a) {
        var key = at.level + "-" + a.subject;
        var g = agg[key] || (agg[key] = { level: at.level, subject: a.subject, total: 0, correct: 0 });
        g.total++;
        if (a.correct) g.correct++;
      });
    });
    var html = "<h3 style='margin:6px 0'>各科累計正確率</h3><table><tr><th>級別</th><th>科目</th><th>正確率</th><th>題數</th></tr>";
    Object.keys(agg).sort().forEach(function (k) {
      var g = agg[k];
      var names = {};
      SUBJECTS[g.level].forEach(function (x) { names[x.id] = x.name; });
      var pct = Math.round(g.correct / g.total * 100);
      html += "<tr><td>" + levelNames[g.level] + "</td><td>科目" + g.subject + " " + esc(names[g.subject] || "") + "</td>"
        + '<td><span class="acc-bar" style="width:' + Math.max(4, pct * 0.8) + 'px"></span>' + pct + "%</td>"
        + "<td>" + g.correct + " / " + g.total + "</td></tr>";
    });
    html += "</table>";

    html += "<h3 style='margin:6px 0'>近期紀錄</h3><table><tr><th>時間</th><th>級別</th><th>範圍</th><th>成績</th></tr>";
    s.attempts.slice(-15).reverse().forEach(function (at) {
      var d = new Date(at.time);
      var scope = at.subject === "all" ? "全科混合" : "科目" + at.subject;
      html += "<tr><td>" + d.toLocaleDateString("zh-TW") + " " + d.toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit" }) + "</td>"
        + "<td>" + levelNames[at.level] + "</td><td>" + scope + "</td><td>" + at.correct + " / " + at.total + "</td></tr>";
    });
    html += "</table>";
    box.innerHTML = html;
    show("view-stats");
  }

  // ---------- 事件 ----------
  Array.prototype.forEach.call(document.querySelectorAll("#level-seg .seg-btn"), function (b) {
    b.onclick = function () {
      state.level = b.getAttribute("data-level");
      state.subject = "all";
      Array.prototype.forEach.call(document.querySelectorAll("#level-seg .seg-btn"), function (x) {
        x.classList.toggle("active", x === b);
      });
      renderSetup();
    };
  });
  $("btn-start").onclick = startQuiz;
  $("btn-next").onclick = next;
  $("btn-quit").onclick = function () {
    showConfirm("要結束這回合嗎?未完成的作答不會計入統計。", function () {
      renderSetup();
      show("view-setup");
      $("btn-start").focus();
    });
  };
  $("btn-again").onclick = startQuiz;
  $("btn-review").onclick = renderReview;
  $("btn-home").onclick = function () { renderSetup(); show("view-setup"); };
  $("nav-home").onclick = function () { renderSetup(); show("view-setup"); };
  $("nav-stats").onclick = renderStats;
  $("btn-clear-stats").onclick = function () {
    showConfirm("確定清除所有作答統計?", function () {
      localStorage.removeItem(STORE_KEY);
      renderStats();
      $("nav-stats").focus();
    });
  };

  renderSetup();
})();
