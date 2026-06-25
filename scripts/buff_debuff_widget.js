(function () {
  "use strict";

  var STATE = {
    phase: "preview",
    datasets: {},
    pageDate: "",
    exactDate: true
  };

  function pageDate() {
    if (window.RDATE) return window.RDATE;
    var m = document.body && document.body.textContent.match(/\d{4}-\d{2}-\d{2}/);
    return m ? m[0] : "";
  }

  function assetPrefix() {
    return location.pathname.indexOf("/manshu/") >= 0 ? "../" : "";
  }

  function keyOf(dateText) {
    return String(dateText || "").replace(/-/g, "");
  }

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function fmtScore(value) {
    if (value == null || value === "") return "--";
    return Number(value).toFixed(1).replace(/\.0$/, "");
  }

  function fmtYen(value) {
    if (value == null || value === "") return "結果待ち";
    return Number(value).toLocaleString("ja-JP") + "円";
  }

  function listLabel(values) {
    if (!values || !values.length) return "--";
    return values.map(function (v) { return v + "号艇"; }).join("・");
  }

  function ticketPreview(tickets) {
    if (!tickets || !tickets.length) return "--";
    var shown = tickets.slice(0, 15);
    return shown.map(function (ticket) {
      return "<span class=\"bd-ticket\">" + esc(ticket) + "</span>";
    }).join("");
  }

  function reasonPreview(text) {
    var parts = String(text || "").split(" / ").filter(Boolean);
    return parts.slice(0, 4).map(function (part) {
      return "<span class=\"bd-reason-line\">" + esc(part) + "</span>";
    }).join("");
  }

  function injectStyle() {
    if (document.getElementById("buff-debuff-widget-style")) return;
    var style = document.createElement("style");
    style.id = "buff-debuff-widget-style";
    style.textContent = [
      ".buff-debuff-card{border-left-color:#0f766e}",
      ".buff-debuff-card h2{color:#0f766e}",
      ".bd-summary{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0 14px}",
      ".bd-chip{background:#ecfdf5;border:1px solid #a7f3d0;border-radius:999px;color:#065f46;font-size:12px;font-weight:800;padding:6px 10px}",
      ".bd-chip.warn{background:#fff7ed;border-color:#fed7aa;color:#9a3412}",
      ".bd-actions{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 12px}",
      ".bd-button{border:1px solid #99f6e4;background:#f0fdfa;color:#0f766e;border-radius:8px;cursor:pointer;font-size:13px;font-weight:800;padding:8px 11px}",
      ".bd-button.active{background:#0f766e;border-color:#0f766e;color:white}",
      ".bd-scroll{overflow-x:auto}",
      ".bd-table{border-collapse:collapse;width:100%;min-width:920px}",
      ".bd-table th,.bd-table td{border-top:1px solid #e5e7eb;padding:10px 8px;text-align:left;vertical-align:top}",
      ".bd-table th{background:#f8fafc;color:#475569;font-size:12px}",
      ".bd-rank{font-size:18px;font-weight:900;color:#0f766e;white-space:nowrap}",
      ".bd-race{font-weight:900;color:#111827;white-space:nowrap}",
      ".bd-score{font-size:20px;font-weight:900;color:#0f766e;white-space:nowrap}",
      ".bd-mini{color:#64748b;font-size:12px;line-height:1.55}",
      ".bd-buy{color:#dc2626;font-weight:900}",
      ".bd-watch{color:#475569;font-weight:800}",
      ".bd-ticket{background:#f1f5f9;border:1px solid #e2e8f0;border-radius:7px;display:inline-block;font-size:12px;font-weight:800;margin:2px 3px 2px 0;padding:4px 6px}",
      ".bd-reason-line{display:block;color:#334155;font-size:12px;line-height:1.55;margin-bottom:2px}",
      ".bd-man{color:#dc2626;font-weight:900}",
      ".bd-miss{color:#475569;font-weight:800}",
      "@media(max-width:760px){.bd-table{min-width:0}.bd-table,.bd-table thead,.bd-table tbody,.bd-table tr,.bd-table th,.bd-table td{display:block}.bd-table thead{display:none}.bd-table tr{border-top:1px solid #e5e7eb;padding:10px 0}.bd-table td{border:0;padding:5px 0}.bd-score{font-size:18px}}"
    ].join("");
    document.head.appendChild(style);
  }

  async function fetchJson(url) {
    try {
      var res = await fetch(url, { cache: "no-store" });
      if (!res.ok) return null;
      return await res.json();
    } catch (e) {
      return null;
    }
  }

  async function loadDateDatasets(dateText) {
    var base = assetPrefix() + "data/output/";
    var key = keyOf(dateText);
    var preview = await fetchJson(base + "buff_debuff_ranking_preview_" + key + ".json?v=bd1");
    var morning = await fetchJson(base + "buff_debuff_ranking_morning_" + key + ".json?v=bd1");
    return { preview: preview, morning: morning };
  }

  async function loadLatestDatasets() {
    var base = assetPrefix() + "data/output/";
    var manifest = await fetchJson(base + "buff_debuff_ranking_latest.json?v=bd1");
    if (!manifest || !manifest.phases) return null;
    var out = {};
    if (manifest.phases.preview) out.preview = await fetchJson(base + manifest.phases.preview + "?v=bd1");
    if (manifest.phases.morning) out.morning = await fetchJson(base + manifest.phases.morning + "?v=bd1");
    return { manifest: manifest, datasets: out };
  }

  function usableData(data) {
    return data && Array.isArray(data.races) && data.races.length;
  }

  function choosePhase() {
    if (usableData(STATE.datasets.preview)) return "preview";
    if (usableData(STATE.datasets.morning)) return "morning";
    return "preview";
  }

  function placeAfterRank(card) {
    var existing = document.getElementById("buff-debuff-card");
    if (existing) existing.remove();
    var anchor = document.querySelector(".card.rank") || document.getElementById("boaters-manshu-card") || document.querySelector("details.card") || document.querySelector("footer");
    if (!anchor || !anchor.parentNode) {
      document.body.appendChild(card);
      return;
    }
    anchor.parentNode.insertBefore(card, anchor.nextSibling);
  }

  function renderMissing(message) {
    var card = document.createElement("section");
    card.id = "buff-debuff-card";
    card.className = "card buff-debuff-card";
    card.innerHTML = [
      "<h2>バフ/デバフ辞書ランキング（検証版）</h2>",
      "<p class=\"lead\">" + esc(message) + "</p>",
      "<p class=\"muted\">競艇場×号艇×データごとのバフ/超バフ/デバフ/超デバフを使い、荒れそうなレース・1号艇危険・外枠絡み・買い目を別系統で表示します。</p>"
    ].join("");
    placeAfterRank(card);
  }

  function rowHtml(race, index) {
    var payout = race.payout;
    var isManshu = Number(race.is_manshu || 0) === 1 || Number(payout || 0) >= 10000;
    var status = race.decision === "買い" ? "<span class=\"bd-buy\">買い</span>" : "<span class=\"bd-watch\">見送り</span>";
    var result = race.result ? esc(race.result) + "<br><span class=\"" + (isManshu ? "bd-man" : "bd-miss") + "\">" + esc(fmtYen(payout)) + (isManshu ? " 万舟" : "") + "</span>" : "<span class=\"bd-mini\">結果待ち</span>";
    var superSlit = race.super_slit_count ? "SSA " + esc(race.super_slit_count) + "艇" : "SSAなし";
    return [
      "<tr>",
      "<td><span class=\"bd-rank\">" + esc(index + 1) + "</span></td>",
      "<td><span class=\"bd-race\">" + esc(race.place_name) + esc(race.round) + "R</span><br><span class=\"bd-mini\">" + esc(race.phase === "preview" ? "展示後" : "朝") + " / " + esc(superSlit) + "</span></td>",
      "<td><span class=\"bd-score\">" + esc(fmtScore(race.buff_manshu_score)) + "</span><br><span class=\"bd-mini\">1号艇危険 " + esc(fmtScore(race.lane1_danger_score)) + "<br>外枠絡み " + esc(fmtScore(race.outer_signal_score)) + "</span></td>",
      "<td>" + status + "<br><span class=\"bd-mini\">頭 " + esc(listLabel(race.heads)) + "<br>軸 " + esc(listLabel(race.axes)) + "<br>消し " + esc(race.keshi ? race.keshi + "号艇" : "--") + "<br>" + esc(race.points || 0) + "点</span></td>",
      "<td><div>" + ticketPreview(race.tickets) + "</div><div class=\"bd-mini\">支持 " + esc(listLabel(race.supports)) + "</div></td>",
      "<td>" + reasonPreview(race.reason) + "</td>",
      "<td>" + result + "</td>",
      "</tr>"
    ].join("");
  }

  function render() {
    var data = STATE.datasets[STATE.phase] || STATE.datasets[choosePhase()];
    if (!usableData(data)) {
      renderMissing("この日のバフ/デバフ辞書ランキングJSONはまだありません。生成されるとここに自動表示されます。");
      return;
    }
    STATE.phase = data.phase || STATE.phase;
    var phaseLabel = STATE.phase === "preview" ? "展示後補正" : "朝ランキング";
    var exactText = STATE.exactDate
      ? "ページ日付 " + data.date + " のランキングです。"
      : "ページ日付 " + STATE.pageDate + " のJSONがないため、直近検証サンプル " + data.date + " を表示中です。";
    var rows = data.races.slice(0, 10);
    var buyCount = rows.filter(function (r) { return r.decision === "買い"; }).length;
    var manshuCount = rows.filter(function (r) { return Number(r.is_manshu || 0) === 1 || Number(r.payout || 0) >= 10000; }).length;
    var card = document.createElement("section");
    card.id = "buff-debuff-card";
    card.className = "card buff-debuff-card";
    card.innerHTML = [
      "<h2>バフ/デバフ辞書ランキング（検証版） TOP10</h2>",
      "<p class=\"lead\"><b>" + esc(phaseLabel) + "</b>。競艇場×号艇×各データのバフ/超バフ/デバフ/超デバフを合成し、1号艇危険・外枠絡み・頭2艇・軸2艇・消し1艇・10〜15点買い目を表示します。</p>",
      "<p class=\"muted\">" + esc(exactText) + " 回収率100%は未確認なので、本番ランキングの置き換えではなく研究版です。</p>",
      "<div class=\"bd-actions\">",
      "<button class=\"bd-button" + (STATE.phase === "morning" ? " active" : "") + "\" data-bd-phase=\"morning\" type=\"button\">朝</button>",
      "<button class=\"bd-button" + (STATE.phase === "preview" ? " active" : "") + "\" data-bd-phase=\"preview\" type=\"button\">展示後</button>",
      "</div>",
      "<div class=\"bd-summary\">",
      "<span class=\"bd-chip\">表示 " + esc(rows.length) + "R</span>",
      "<span class=\"bd-chip\">買い " + esc(buyCount) + "R</span>",
      "<span class=\"bd-chip\">万舟 " + esc(manshuCount) + "R</span>",
      "<span class=\"bd-chip warn\">検証版</span>",
      "</div>",
      "<div class=\"bd-scroll\"><table class=\"bd-table\"><thead><tr><th>順位</th><th>レース</th><th>スコア</th><th>候補</th><th>買い目</th><th>根拠</th><th>結果</th></tr></thead><tbody>",
      rows.map(rowHtml).join(""),
      "</tbody></table></div>",
      "<p class=\"muted\">※この表は保存済みBOATERS由来データから作った研究版です。利益保証ではありません。日付別JSONが生成済みの日はその日の内容に自動で切り替わります。</p>"
    ].join("");
    placeAfterRank(card);
    Array.prototype.slice.call(card.querySelectorAll("[data-bd-phase]")).forEach(function (button) {
      button.addEventListener("click", function () {
        var next = button.getAttribute("data-bd-phase");
        if (!usableData(STATE.datasets[next])) return;
        STATE.phase = next;
        render();
      });
    });
  }

  async function load() {
    injectStyle();
    STATE.pageDate = pageDate();
    if (!STATE.pageDate) {
      renderMissing("ページ日付を取得できなかったため、バフ/デバフ辞書ランキングを読み込めませんでした。");
      return;
    }
    STATE.datasets = await loadDateDatasets(STATE.pageDate);
    STATE.exactDate = usableData(STATE.datasets.preview) || usableData(STATE.datasets.morning);
    if (!STATE.exactDate) {
      var latest = await loadLatestDatasets();
      if (latest && latest.datasets) {
        STATE.datasets = latest.datasets;
        STATE.exactDate = false;
      }
    }
    STATE.phase = choosePhase();
    render();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", load);
  } else {
    load();
  }
})();
