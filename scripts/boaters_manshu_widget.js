(function () {
  "use strict";

  function pageDate() {
    if (window.RDATE) return window.RDATE;
    var m = document.body && document.body.textContent.match(/\d{4}-\d{2}-\d{2}/);
    return m ? m[0] : "";
  }

  function assetPrefix() {
    return location.pathname.indexOf("/manshu/") >= 0 ? "../" : "";
  }

  function dataUrl(date) {
    return assetPrefix() + "data/output/boaters_manshu_ranking_" + date.replace(/-/g, "") + ".json";
  }

  function fmtPct(v) {
    return v == null ? "--" : Number(v).toFixed(2).replace(/\.00$/, "") + "%";
  }

  function fmtSec(v) {
    return v == null ? "--" : Number(v).toFixed(2).replace(/0$/, "").replace(/\.0$/, "");
  }

  function fmtYen(v) {
    return v == null ? "結果待ち" : Number(v).toLocaleString("ja-JP") + "円";
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function injectStyle() {
    if (document.getElementById("boaters-manshu-style")) return;
    var style = document.createElement("style");
    style.id = "boaters-manshu-style";
    style.textContent = [
      ".boaters-manshu{border-left-color:#dc2626;position:relative;overflow:hidden}",
      ".boaters-manshu h2{color:#991b1b}",
      ".boaters-manshu .bm-summary{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 14px}",
      ".boaters-manshu .bm-chip{background:#fff7ed;border:1px solid #fed7aa;border-radius:999px;color:#9a3412;font-size:12px;font-weight:700;padding:6px 10px}",
      ".boaters-manshu .bm-chip.hot{background:#fee2e2;border-color:#fecaca;color:#991b1b}",
      ".boaters-manshu .bm-table{width:100%;border-collapse:collapse;margin-top:8px}",
      ".boaters-manshu .bm-table th,.boaters-manshu .bm-table td{border-top:1px solid #e5e7eb;padding:9px 8px;text-align:left;vertical-align:top}",
      ".boaters-manshu .bm-table th{font-size:12px;color:#475569;background:#f8fafc}",
      ".boaters-manshu .bm-rate{font-size:20px;font-weight:800;color:#dc2626;white-space:nowrap}",
      ".boaters-manshu .bm-race{font-weight:800;color:#111827;white-space:nowrap}",
      ".boaters-manshu .bm-cond{color:#374151;font-size:13px;line-height:1.45;max-width:680px}",
      ".boaters-manshu .bm-mini{color:#64748b;font-size:12px;line-height:1.55}",
      ".boaters-manshu .bm-hit{color:#dc2626;font-weight:800}",
      ".boaters-manshu .bm-miss{color:#475569;font-weight:700}",
      "@media(max-width:720px){.boaters-manshu .bm-table,.boaters-manshu .bm-table thead,.boaters-manshu .bm-table tbody,.boaters-manshu .bm-table tr,.boaters-manshu .bm-table th,.boaters-manshu .bm-table td{display:block}.boaters-manshu .bm-table thead{display:none}.boaters-manshu .bm-table tr{border-top:1px solid #e5e7eb;padding:10px 0}.boaters-manshu .bm-table td{border:0;padding:4px 0}.boaters-manshu .bm-rate{font-size:18px}}"
    ].join("");
    document.head.appendChild(style);
  }

  function raceRow(r) {
    var result = r.result || {};
    var metrics = r.metrics || {};
    var manshu = result.manshu;
    var deadline = r.deadline_time ? String(r.deadline_time).slice(11, 16) : "--:--";
    return [
      "<tr>",
      "<td><span class=\"bm-rate\">" + esc(fmtPct(r.manshu_rate_pct)) + "</span><br><span class=\"bm-mini\">直近 " + esc(fmtPct(r.recent_rate_pct)) + "</span></td>",
      "<td><span class=\"bm-race\">" + esc(r.rank) + ". " + esc(r.place_name) + esc(r.round) + "R</span><br><span class=\"bm-mini\">" + esc(deadline) + "締切 / ロジック" + esc(r.matched_logic_count) + "件</span></td>",
      "<td class=\"bm-cond\">" + esc(r.condition) + "<br><span class=\"bm-mini\">1号艇 AI予測 " + esc(fmtPct(metrics.boat1_ai_prediction_pct)) + " / AI+一般3連対 " + esc(fmtPct(metrics.boat1_ai_plus)) + " / 展示 " + esc(fmtSec(metrics.boat1_tenji_time)) + " / 1周 " + esc(fmtSec(metrics.boat1_isshu_time)) + " / 5・6号艇最速 1周 " + esc(fmtSec(metrics.outer56_best_isshu_time)) + "</span></td>",
      "<td><b>" + esc(result.trifecta || "--") + "</b><br><span class=\"" + (manshu ? "bm-hit" : "bm-miss") + "\">" + esc(fmtYen(result.payout_yen)) + (manshu ? " 万舟" : "") + "</span></td>",
      "</tr>"
    ].join("");
  }

  function render(data) {
    var oldRank = document.querySelector(".card.rank");
    if (!oldRank || document.getElementById("boaters-manshu-card")) return;
    var summary = data.summary || {};
    var section = document.createElement("section");
    section.id = "boaters-manshu-card";
    section.className = "card boaters-manshu";
    section.innerHTML = [
      "<h2>BOATERS展示ロジック 万舟率ランキング TOP5</h2>",
      "<p class=\"lead\"><b>" + esc(data.logic_label || "BOATERS展示込みロジック") + "</b>で算出。AI+一般3連対、1号艇の逃げ/飛び傾向、差され・まくられ率、展示タイム・1周タイムを使い、過去検証で万舟率" + esc(fmtPct(data.threshold_pct)) + "以上だった条件に一致したレースだけを上位表示しています。</p>",
      "<div class=\"bm-summary\">",
      "<span class=\"bm-chip hot\">TOP" + esc(summary.displayed_top_n || 0) + " 実測 " + esc(fmtPct(summary.actual_manshu_rate_top_n_pct)) + "</span>",
      "<span class=\"bm-chip\">万舟 " + esc(summary.manshu_hits_top_n || 0) + "/" + esc(summary.settled_top_n || 0) + "本</span>",
      "<span class=\"bm-chip\">展示6艇取得 " + esc(summary.races_with_full_tenji || 0) + "R</span>",
      "<span class=\"bm-chip\">1周6艇取得 " + esc(summary.races_with_full_isshu || 0) + "R</span>",
      "</div>",
      "<table class=\"bm-table\"><thead><tr><th>万舟率</th><th>レース</th><th>該当ロジック・展示根拠</th><th>結果</th></tr></thead><tbody>",
      (data.races || []).map(raceRow).join(""),
      "</tbody></table>",
      "<p class=\"muted\">※これは万舟が出やすい条件のランキングです。買い目や利益を保証するものではありません。</p>"
    ].join("");
    oldRank.parentNode.insertBefore(section, oldRank);
  }

  async function load() {
    injectStyle();
    var date = pageDate();
    if (!date) return;
    try {
      var res = await fetch(dataUrl(date), { cache: "no-store" });
      if (!res.ok) return;
      render(await res.json());
    } catch (e) {
      // Static pages remain usable if the BOATERS JSON has not been generated yet.
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", load);
  } else {
    load();
  }
})();
