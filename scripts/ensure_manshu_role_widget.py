#!/usr/bin/env python3
"""Ensure generated manshu HTML pages include the top ranking/post widgets.

The daily manshu generator rewrites manshu.html and date archive pages. This
script is intentionally idempotent so it can run after generated commits and
restore the ranking/result post widgets without changing prediction logic.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ROLE_CSS = """.rate-scroll{overflow-x:auto;margin-top:8px}
.rate-table{min-width:760px}
.rate-table th,.rate-table td{vertical-align:top}
.rate-table .race{font-weight:800;color:#33405a;white-space:nowrap}
.rate-table .rate{font-weight:900;color:#7c3aed;white-space:nowrap}
.rate-table .result{white-space:nowrap}
.rate-table .roi{font-weight:900;color:#047857;white-space:nowrap}
.rate-table .miss{color:#64748b;font-weight:800}
.rate-summary{font-size:12.5px;color:#33405a;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:8px 10px;margin:8px 0 0}
.pickrow td{padding:0 0 8px;background:#faf8ff;border-bottom:1px solid #e9d5ff}
.pickpanel{border:1px solid #ddd6fe;background:#fff;border-radius:8px;margin:6px 4px 0;padding:9px 10px}
.pickgrid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
.pickbox{border:1px solid #eef1f5;background:#fff;border-radius:8px;padding:7px 8px;font-size:12.5px;line-height:1.45}
.pickbox b{color:#33405a}.picktag{display:block;font-weight:900;font-size:11.5px;margin-bottom:4px}
.pickbox.head{background:#fff7ed;border-color:#fed7aa}.pickbox.head .picktag{color:#b91c1c}
.pickbox.axis{background:#eff6ff;border-color:#bfdbfe}.pickbox.axis .picktag{color:#1d4ed8}
.pickbox.toss{background:#f8fafc;border-color:#cbd5e1}.pickbox.toss .picktag{color:#475569}
.pickhint{font-size:11.5px;color:#64748b;margin-top:7px}
@media(max-width:640px){.pickgrid{grid-template-columns:1fr}}
.post-card textarea{min-height:150px}"""


RATE_CARD = """<div class="card rank" id="rate-card">
  <h2>📊 万舟率トップ10（結果つき）</h2>
  <p class="lead" id="rate-status">本日の万舟率トップ10を読み込み中…</p>
  <div class="bar"><button id="rbtn" onclick="loadResults()">🔄 結果を更新</button><span id="rstat" class="rstat"></span></div>
  <div class="rate-scroll">
    <table class="rate-table">
      <thead><tr><th>順位</th><th>場R</th><th>万舟率</th><th>結果</th><th>買い方1</th><th>単発回収率</th></tr></thead>
      <tbody id="rate-list"></tbody>
    </table>
  </div>
  <p class="rate-summary" id="rate-summary">集計待ち</p>
  <p class="muted">的中・回収率は「買い方1（検証用9点）」を100円ずつ買った場合の単発換算です。予想・購入推奨・利益保証ではありません。</p>
</div>
<div class="card xpost post-card" id="top5-x-card">
  <h2>✍️ X投稿用｜ランキング</h2>
  <p class="lead">ランキングだけを短文で投稿できます。結果・買い目・回収率は載せません。</p>
  <textarea class="xta" id="top5-x-rank-post" rows="8" readonly>読み込み中…</textarea>
  <button class="xcopy" onclick="copyX('top5-x-rank-post',this)">📋 Xランキング文をコピー</button><span id="top5-x-rank-post-len" class="xlen"></span>
</div>
<div class="card xpost post-card" id="top5-x-result-card">
  <h2>✍️ X投稿用｜結果</h2>
  <p class="lead">ランキング投稿とは分けて、結果の答え合わせだけを投稿できます。</p>
  <textarea class="xta" id="top5-x-result-post" rows="8" readonly>読み込み中…</textarea>
  <button class="xcopy" onclick="copyX('top5-x-result-post',this)">📋 X結果文をコピー</button><span id="top5-x-result-post-len" class="xlen"></span>
</div>
<div class="card notepost post-card" id="top10-note-card">
  <h2>📝 note投稿用｜ランキング</h2>
  <p class="lead">トップ10のランキング本文です。結果は別投稿に分けます。</p>
  <textarea class="xta" id="top10-note-rank-post" rows="18" readonly>読み込み中…</textarea>
  <button class="xcopy" onclick="copyX('top10-note-rank-post',this)">📋 noteランキング文をコピー</button>
</div>
<div class="card notepost post-card" id="top10-note-result-card">
  <h2>📝 note投稿用｜結果</h2>
  <p class="lead">トップ10の答え合わせ本文です。ランキング投稿とは別に使えます。</p>
  <textarea class="xta" id="top10-note-result-post" rows="18" readonly>読み込み中…</textarea>
  <button class="xcopy" onclick="copyX('top10-note-result-post',this)">📋 note結果文をコピー</button>
</div>"""


POST_CARDS = """<div class="card xpost post-card" id="top5-x-card">
  <h2>✍️ X投稿用｜ランキング</h2>
  <p class="lead">ランキングだけを短文で投稿できます。結果・買い目・回収率は載せません。</p>
  <textarea class="xta" id="top5-x-rank-post" rows="8" readonly>読み込み中…</textarea>
  <button class="xcopy" onclick="copyX('top5-x-rank-post',this)">📋 Xランキング文をコピー</button><span id="top5-x-rank-post-len" class="xlen"></span>
</div>
<div class="card xpost post-card" id="top5-x-result-card">
  <h2>✍️ X投稿用｜結果</h2>
  <p class="lead">ランキング投稿とは分けて、結果の答え合わせだけを投稿できます。</p>
  <textarea class="xta" id="top5-x-result-post" rows="8" readonly>読み込み中…</textarea>
  <button class="xcopy" onclick="copyX('top5-x-result-post',this)">📋 X結果文をコピー</button><span id="top5-x-result-post-len" class="xlen"></span>
</div>
<div class="card notepost post-card" id="top10-note-card">
  <h2>📝 note投稿用｜ランキング</h2>
  <p class="lead">トップ10のランキング本文です。結果は別投稿に分けます。</p>
  <textarea class="xta" id="top10-note-rank-post" rows="18" readonly>読み込み中…</textarea>
  <button class="xcopy" onclick="copyX('top10-note-rank-post',this)">📋 noteランキング文をコピー</button>
</div>
<div class="card notepost post-card" id="top10-note-result-card">
  <h2>📝 note投稿用｜結果</h2>
  <p class="lead">トップ10の答え合わせ本文です。ランキング投稿とは別に使えます。</p>
  <textarea class="xta" id="top10-note-result-post" rows="18" readonly>読み込み中…</textarea>
  <button class="xcopy" onclick="copyX('top10-note-result-post',this)">📋 note結果文をコピー</button>
</div>"""


ROLE_JS = """var ROLE_RANKING_DATA=null;
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function roleDataUrl(){
  var prefix=location.pathname.indexOf('/manshu/')>=0?'../':'';
  return prefix+'data/output/manshu_role_ranking_'+RDATE.replace(/-/g,'')+'.json';
}
function roleResultKey(r){return parseInt(r.jcd,10)+'-'+parseInt(r.race_no,10);}
function roleResultHtml(r){
  var live=ROLE_RESULT_MAP[roleResultKey(r)],res=r.result||{},combo=null,payout=null;
  if(live){combo=live.combination; payout=live.payout;}
  else {combo=res.trifecta; payout=res.payout_yen;}
  if(!combo) return '結果: <span class="muted">未確定</span>';
  if(payout==null) return '結果: 3連単 <b>'+esc(combo)+'</b> <span class="muted">配当待ち</span>';
  var man=payout>=MAN;
  return '結果: 3連単 <b>'+esc(combo)+'</b> '+Number(payout).toLocaleString()+'円 '+(man?'<span class="man">万舟決着</span>':'<span class="muted">1万円未満</span>');
}
function pctText(v){return v==null?'—':(Number(v)*100).toFixed(1)+'%';}
function pctPoint(v){return v==null?'—':(Number(v)*100).toFixed(1)+'%';}
function yenText(v){return v==null?'—':Number(v).toLocaleString()+'円';}
function rateResult(r){
  var live=ROLE_RESULT_MAP[roleResultKey(r)],res=r.result||{},combo=null,payout=null,status=null;
  if(live){combo=live.combination; payout=live.payout; status='live';}
  else {combo=res.trifecta; payout=res.payout_yen; status=res.status||null;}
  return {combination:combo,payout:payout,manshu:payout!=null&&payout>=MAN,status:status};
}
function strategyEval(r){
  var s=r.strategy&&r.strategy.buy_style_1||{},form=s.formation||{},tickets=form.tickets||[];
  var points=Number(form.points||tickets.length||9),cost=points*100,result=rateResult(r),check=s.result_check||{};
  var hit=check.hit,ret=check.return_yen_per_100;
  if(hit==null&&result.combination&&result.payout!=null&&tickets.length){
    hit=tickets.indexOf(result.combination)>=0;
    ret=hit?result.payout:0;
  }
  if(result.combination&&!result.payout&&hit==null) return {points:points,cost:cost,done:false,hit:null,returnYen:null,roi:null,label:'配当待ち',short:'待'};
  if(!result.combination&&hit==null) return {points:points,cost:cost,done:false,hit:null,returnYen:null,roi:null,label:'結果待ち',short:'待'};
  if(ret==null) ret=hit?result.payout:0;
  var roi=cost?ret/cost*100:null;
  return {points:points,cost:cost,done:true,hit:!!hit,returnYen:ret,roi:roi,label:hit?'的中':'不的中',short:hit?'◎':'×'};
}
function topRateRaces(data){
  return (data.races||[]).slice().sort(function(a,b){
    return (b.scores&&b.scores.manshu_probability_proxy||0)-(a.scores&&a.scores.manshu_probability_proxy||0);
  }).slice(0,10);
}
function summarizeTop(top){
  var done=0,manshu=0,hit=0,cost=0,ret=0,pending=0;
  top.forEach(function(r){
    var res=rateResult(r),ev=strategyEval(r);
    if(res.combination&&res.payout!=null){
      done++;
      if(res.manshu) manshu++;
    } else pending++;
    if(ev.done){
      cost+=ev.cost;
      ret+=ev.returnYen||0;
      if(ev.hit) hit++;
    }
  });
  return {done:done,pending:pending,manshu:manshu,hit:hit,cost:cost,ret:ret,roi:cost?ret/cost*100:null};
}
function resultCellText(r){
  var res=rateResult(r);
  if(!res.combination) return '結果待ち';
  if(res.payout==null) return res.combination+' 配当待ち';
  return res.combination+' '+yenText(res.payout)+' '+(res.manshu?'万舟決着':'1万円未満');
}
function compactRaceLabel(r){return esc(r.venue_name||'')+esc(r.race_no)+'R';}
function roleBoat(r,lane){
  return (r.boats||[]).find(function(b){return Number(b.lane)===Number(lane);})||{lane:lane};
}
function pickLine(r,lane){
  var b=roleBoat(r,lane),name=b.name?' '+esc(b.name):'', cls=b.class?' <span class="muted">'+esc(b.class)+'</span>':'';
  var score=b.role_score==null?'':' <span class="muted">score '+Math.round(Number(b.role_score))+'</span>';
  var reason=b.role_reason?'<br><span class="muted">'+esc(b.role_reason).replace(/\\|/g,' / ')+'</span>':'';
  return '<div><b>'+esc(lane)+'号艇</b>'+name+cls+score+reason+'</div>';
}
function pickBox(r,key,label){
  var lanes=(r.role_summary&&r.role_summary[key])||[];
  var body=lanes.length?lanes.map(function(lane){return pickLine(r,lane);}).join(''):'<span class="muted">未判定</span>';
  return '<div class="pickbox '+key+'"><span class="picktag">'+label+'</span>'+body+'</div>';
}
function pickDetailsHtml(r){
  return '<div class="pickpanel">'+
    '<div class="pickgrid">'+
      pickBox(r,'head','頭候補')+
      pickBox(r,'axis','軸候補')+
      pickBox(r,'toss','消し候補')+
    '</div>'+
    '<div class="pickhint">行をもう一度押すと閉じます。役割表示は過去データから作った補助情報で、買い目・購入推奨ではありません。</div>'+
  '</div>';
}
function toggleRatePick(key){
  var row=document.getElementById('pick-'+key);
  if(!row) return;
  var open=row.style.display==='none';
  row.style.display=open?'':'none';
  document.querySelectorAll('[data-rate-caret="'+key+'"]').forEach(function(el){el.textContent=open?'▼':'▶';});
}
function updateRateResults(){
  if(!ROLE_RANKING_DATA) return;
  renderRateTop10(ROLE_RANKING_DATA);
}
function renderRateTop10(data){
  ROLE_RANKING_DATA=data;
  var body=document.getElementById('rate-list'),status=document.getElementById('rate-status'),summaryEl=document.getElementById('rate-summary');
  if(!body||!status) return;
  var top=topRateRaces(data),summary=summarizeTop(top);
  if(!top.length){status.textContent='万舟率トップ10データが空です。'; return;}
  status.textContent='万舟率が高い順にトップ10を表示中。結果は確定分から順次反映します。';
  body.innerHTML=top.map(function(r,i){
    var res=rateResult(r),ev=strategyEval(r),rate=pctPoint(r.scores&&r.scores.manshu_probability_proxy);
    var resultHtml=!res.combination?'<span class="muted">結果待ち</span>':
      esc(res.combination)+'<br><span class="'+(res.manshu?'man':'muted')+'">'+(res.payout==null?'配当待ち':yenText(res.payout)+(res.manshu?' 万舟決着':' 1万円未満'))+'</span>';
    var hitHtml=ev.hit==null?'<span class="muted">'+esc(ev.label)+'</span>':
      '<span class="'+(ev.hit?'man':'miss')+'">'+esc(ev.label)+'</span><br><span class="muted">'+ev.points+'点</span>';
    var roiHtml=ev.roi==null?'<span class="muted">—</span>':'<span class="roi">'+Math.round(ev.roi)+'%</span><br><span class="muted">返 '+yenText(ev.returnYen)+'</span>';
    var key=esc(roleResultKey(r));
    return '<tr class="rrow" data-rate-row="'+key+'" onclick="toggleRatePick(\\''+key+'\\')">'+
      '<td class="rkn">'+(i+1)+'</td>'+
      '<td><span class="race">'+compactRaceLabel(r)+' <span class="caret" data-rate-caret="'+key+'">▶</span></span><br><span class="muted">'+esc(r.deadline||'')+'</span></td>'+
      '<td class="rate">'+rate+'</td>'+
      '<td class="result">'+resultHtml+'</td>'+
      '<td>'+hitHtml+'</td>'+
      '<td>'+roiHtml+'</td>'+
    '</tr><tr class="pickrow" id="pick-'+key+'" style="display:none"><td colspan="6">'+pickDetailsHtml(r)+'</td></tr>';
  }).join('');
  if(summaryEl){
    summaryEl.innerHTML='トップ10確定 '+summary.done+'/'+top.length+'R / 万舟決着 '+summary.manshu+'件 / 検証用9点 '+summary.hit+'件 / 単発回収率 <b>'+(summary.roi==null?'—':Math.round(summary.roi)+'%')+'</b>（返戻 '+yenText(summary.ret)+' / 想定購入 '+yenText(summary.cost)+'）';
  }
  buildTopPosts(top,summary);
}
function buildTopPosts(top,summary){
  var xr=document.getElementById('top5-x-rank-post'),xx=document.getElementById('top5-x-result-post');
  var nr=document.getElementById('top10-note-rank-post'),nx=document.getElementById('top10-note-result-post');
  var md=RDATE.slice(5).replace('-','/');
  var top5=top.slice(0,5),top5Done=0,top5Manshu=0;
  top5.forEach(function(r){var res=rateResult(r); if(res.combination&&res.payout!=null){top5Done++; if(res.manshu) top5Manshu++;}});
  if(xr){
    var xlines=[md+' 万舟率TOP5 観察メモ','万舟率=荒れやすさの研究用指標',''];
    top5.forEach(function(r,i){
      var rate=Math.round((r.scores&&r.scores.manshu_probability_proxy||0)*100);
      xlines.push((i+1)+'. '+compactRaceLabel(r).replace(/<[^>]*>/g,'')+' 万舟率'+rate+'%'+(r.deadline?'（'+r.deadline+'）':''));
    });
    xlines.push('','結果は別投稿で答え合わせ。買い目・購入推奨・利益保証なし。','#ボートレース #データ分析');
    xr.value=xlines.join('\\\\n');
    showLen('top5-x-rank-post');
  }
  if(xx){
    var rx=[md+' 万舟率TOP5 答え合わせ','確定 '+top5Done+'/'+top5.length+'R / 万舟決着 '+top5Manshu+'件',''];
    top5.forEach(function(r,i){
      var res=rateResult(r),rate=Math.round((r.scores&&r.scores.manshu_probability_proxy||0)*100);
      var result=res.payout==null?(res.combination?'結果 '+res.combination+' 配当待ち':'結果待ち'):('結果 '+res.combination+' '+Number(res.payout).toLocaleString()+'円'+(res.manshu?' 万舟決着':' 1万円未満'));
      rx.push((i+1)+'. '+compactRaceLabel(r).replace(/<[^>]*>/g,'')+' 万舟率'+rate+'% / '+result);
    });
    rx.push('','ランキング投稿とは分けた答え合わせ。買い目・購入推奨・利益保証なし。','#ボートレース #データ分析');
    xx.value=rx.join('\\\\n');
    showLen('top5-x-result-post');
  }
  if(nr){
    var L=['# '+md+' 万舟率TOP10 観察メモ','','過去データから作った「荒れやすさ」のランキングです。結果は別投稿で答え合わせします。買い目、購入推奨、利益保証ではありません。','','## TOP10'];
    top.forEach(function(r,i){
      var res=rateResult(r),rate=pctPoint(r.scores&&r.scores.manshu_probability_proxy);
      L.push('');
      L.push('### '+(i+1)+'位 '+(r.venue_name||'')+r.race_no+'R（'+(r.deadline||'締切未取得')+'）');
      L.push('- 万舟率: '+rate);
    });
    L.push('');
    L.push('## 注意');
    L.push('- 万舟率は荒れやすさの目安で、的中や利益を示す数字ではありません。');
    L.push('- 結果・払戻はランキング投稿には含めません。');
    L.push('- 娯楽・研究用です。舟券購入を推奨しません。');
    nr.value=L.join('\\\\n');
  }
  if(nx){
    var R=['# '+md+' 万舟率TOP10 答え合わせ','','ランキングTOP10が実際にどう決着したかを見る観察記録です。','','## 集計','- 確定: '+summary.done+'/'+top.length+'R','- 万舟決着: '+summary.manshu+'件','','## TOP10 結果'];
    top.forEach(function(r,i){
      var rate=pctPoint(r.scores&&r.scores.manshu_probability_proxy);
      R.push('');
      R.push('### '+(i+1)+'位 '+(r.venue_name||'')+r.race_no+'R（万舟率 '+rate+'）');
      R.push('- 結果: '+resultCellText(r));
    });
    R.push('');
    R.push('## 注意');
    R.push('- 結果・払戻は答え合わせ用で、購入判断を促すものではありません。');
    R.push('- 買い目、購入推奨、利益保証は含みません。');
    R.push('- 娯楽・研究用の記録です。');
    nx.value=R.join('\\\\n');
  }
}
function renderRoleRanking(data){
  ROLE_RANKING_DATA=data;
  renderRateTop10(data);
}
async function loadRoleRanking(){
  var status=document.getElementById('rate-status');
  try{
    var r=await fetch(roleDataUrl(),{cache:'no-store'});
    if(!r.ok) throw 0;
    renderRoleRanking(await r.json());
  }catch(e){
    if(status) status.textContent='本日の万舟率トップ10 JSONはまだ未生成です。';
  }
}"""


def default_targets(root: Path) -> list[Path]:
    paths = [root / "manshu.html"]
    paths.extend(sorted((root / "manshu").glob("*.html")))
    return [path for path in paths if path.exists()]


def patch_html(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    original = text
    if 'var RDATE="' not in text:
        print(f"skip unsupported manshu page: {path}")
        return False
    if ".card.role" not in text and not any(
        marker in text
        for marker in [
            ".card.rank{border-left-color:#7c3aed} .card.rank h2{color:#6d28d9}\n",
            "footer{color:#8a93a6;font-size:11.5px;text-align:center;margin-top:20px}\n",
        ]
    ):
        print(f"skip unsupported manshu page: {path} (CSS marker not found)")
        return False
    if 'id="role-card"' not in text and not any(
        [
            re.search(r'(<div class="bar">.*?</div>\n)(<div class="card rank">)', text, flags=re.S),
            re.search(r'(<p class="sub">📅 .*?</p>\n)', text, flags=re.S),
            re.search(r'(<details class="card">)', text),
        ]
    ):
        print(f"skip unsupported manshu page: {path} (role card marker not found)")
        return False
    if "var ROLE_RESULT_MAP={};" not in text and not re.search(r'(var RDATE="[^"]+", MAN=10000;\n)', text):
        print(f"skip unsupported manshu page: {path} (RDATE marker not found)")
        return False
    if "function roleDataUrl()" not in text and "function acc(tr){" not in text:
        print(f"skip unsupported manshu page: {path} (JS marker not found)")
        return False
    if "ROLE_RESULT_MAP=map;" not in text and "  var done=0,man=0,total=0,pend=0;" not in text:
        print(f"skip unsupported manshu page: {path} (loadResults marker not found)")
        return False
    if (
        "loadRoleRanking()" not in text.split("document.addEventListener('DOMContentLoaded'", 1)[-1]
        and "showLen('xrank'); loadTimes();" not in text
        and "showLen('xrank');" not in text
    ):
        print(f"skip unsupported manshu page: {path} (DOMContentLoaded marker not found)")
        return False

    if ".rate-scroll" not in text:
        marker = ".card.rank{border-left-color:#7c3aed} .card.rank h2{color:#6d28d9}\n"
        if marker in text:
            text = text.replace(marker, marker + ROLE_CSS + "\n", 1)
        else:
            marker = "footer{color:#8a93a6;font-size:11.5px;text-align:center;margin-top:20px}\n"
            text = text.replace(marker, ROLE_CSS + "\n" + marker, 1)
    elif ".role-strategy" not in text:
        text = text.replace(
            ".role-result{font-weight:800;color:#33405a}",
            """.role-result{font-weight:800;color:#33405a}
.role-strategy{margin-top:7px;border:1px solid #e5e7eb;background:#fafafa;border-radius:8px;padding:7px 8px;font-size:12px;line-height:1.5;color:#374151}
.role-strategy b{color:#111827}.role-strategy .good{color:#047857;font-weight:900}.role-strategy .hold{color:#b45309;font-weight:900}.role-strategy .avoid{color:#b91c1c;font-weight:900}.role-strategy .outside_rule{color:#64748b;font-weight:900}""",
            1,
        )
    elif ".rate-table" not in text:
        marker = ".role-strategy b{color:#111827}.role-strategy .good{color:#047857;font-weight:900}.role-strategy .hold{color:#b45309;font-weight:900}.role-strategy .avoid{color:#b91c1c;font-weight:900}.role-strategy .outside_rule{color:#64748b;font-weight:900}"
        text = text.replace(
            marker,
            marker
            + """
.rate-scroll{overflow-x:auto;margin-top:8px}
.rate-table{min-width:760px}
.rate-table th,.rate-table td{vertical-align:top}
.rate-table .race{font-weight:800;color:#33405a;white-space:nowrap}
.rate-table .rate{font-weight:900;color:#7c3aed;white-space:nowrap}
.rate-table .result{white-space:nowrap}
.rate-table .roi{font-weight:900;color:#047857;white-space:nowrap}
.rate-table .miss{color:#64748b;font-weight:800}
.rate-roles{font-size:11.8px;line-height:1.55;color:#475569;min-width:220px;max-width:320px}
.rate-roles b{color:#33405a}
.rate-summary{font-size:12.5px;color:#33405a;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:8px 10px;margin:8px 0 0}
.post-card textarea{min-height:150px}""",
            1,
        )
    elif ".rate-roles" not in text:
        text = text.replace(".rate-table{min-width:720px}", ".rate-table{min-width:760px}", 1)
        text, count = re.subn(
            r"\.rate-tickets\{[^}]+\}",
            """.rate-roles{font-size:11.8px;line-height:1.55;color:#475569;min-width:220px;max-width:320px}
.rate-roles b{color:#33405a}""",
            text,
            count=1,
        )
        if count != 1:
            text = text.replace(
                ".rate-table .miss{color:#64748b;font-weight:800}",
                """.rate-table .miss{color:#64748b;font-weight:800}
.rate-roles{font-size:11.8px;line-height:1.55;color:#475569;min-width:220px;max-width:320px}
.rate-roles b{color:#33405a}""",
                1,
            )

    text = text.replace(".rate-table{min-width:980px}", ".rate-table{min-width:760px}")
    while ROLE_CSS + "\n" + ROLE_CSS in text:
        text = text.replace(ROLE_CSS + "\n" + ROLE_CSS, ROLE_CSS)
    if ".pickgrid" not in text:
        text = text.replace(
            ".post-card textarea{min-height:150px}",
            """.pickrow td{padding:0 0 8px;background:#faf8ff;border-bottom:1px solid #e9d5ff}
.pickpanel{border:1px solid #ddd6fe;background:#fff;border-radius:8px;margin:6px 4px 0;padding:9px 10px}
.pickgrid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
.pickbox{border:1px solid #eef1f5;background:#fff;border-radius:8px;padding:7px 8px;font-size:12.5px;line-height:1.45}
.pickbox b{color:#33405a}.picktag{display:block;font-weight:900;font-size:11.5px;margin-bottom:4px}
.pickbox.head{background:#fff7ed;border-color:#fed7aa}.pickbox.head .picktag{color:#b91c1c}
.pickbox.axis{background:#eff6ff;border-color:#bfdbfe}.pickbox.axis .picktag{color:#1d4ed8}
.pickbox.toss{background:#f8fafc;border-color:#cbd5e1}.pickbox.toss .picktag{color:#475569}
.pickhint{font-size:11.5px;color:#64748b;margin-top:7px}
@media(max-width:640px){.pickgrid{grid-template-columns:1fr}}
.post-card textarea{min-height:150px}""",
            1,
        )

    role_css_patterns = [
        r"\.card\.role\{[^}]+\} \.card\.role h2\{[^}]+\}\n?",
        r"\.rolelist\{[^}]+\}\n?",
        r"\.roleitem\{[^}]+\}\n?",
        r"\.roletop\{[^}]+\}\n?",
        r"\.rolemetric\{[^}]+\}\n?",
        r"\.rolegrid\{[^}]+\}\n?",
        r"\.rolebox\{[^}]+\}\n?",
        r"\.rolebox b\{[^}]+\}\.rolebox \.tag\{[^}]+\}\n?",
        r"\.rolebox\.toss \.tag\{[^}]+\}\.rolebox\.toss\{[^}]+\}\n?",
        r"\.rolebox\.head \.tag\{[^}]+\}\.rolebox\.head\{[^}]+\}\n?",
        r"\.rolebox\.axis \.tag\{[^}]+\}\.rolebox\.axis\{[^}]+\}\n?",
        r"\.rolefoot\{[^}]+\}\n?",
        r"\.role-result\{[^}]+\}\n?",
        r"\.role-strategy\{[^}]+\}\n?",
        r"\.role-strategy b\{[^}]+\}\.role-strategy \.good\{[^}]+\}\.role-strategy \.hold\{[^}]+\}\.role-strategy \.avoid\{[^}]+\}\.role-strategy \.outside_rule\{[^}]+\}\n?",
    ]
    for pattern in role_css_patterns:
        text = re.sub(pattern, "", text)

    text = re.sub(
        r'\n?<div class="card role" id="role-card">\s*<h2>.*?</h2>\s*<p class="lead" id="role-status">.*?</p>\s*<div class="rolelist" id="role-list"></div>\s*<p class="muted">.*?</p>\s*</div>\n?',
        "\n",
        text,
        count=1,
        flags=re.S,
    )

    if 'id="rate-card"' not in text:
        count = 0
        if 'id="role-card"' in text:
            text, count = re.subn(
                r'(<div class="card role" id="role-card">)',
                RATE_CARD + "\n" + r"\1",
                text,
                count=1,
            )
        if count != 1:
            text, count = re.subn(
                r'(<p class="sub">📅 .*?</p>\n)',
                r"\1" + RATE_CARD + "\n",
                text,
                count=1,
                flags=re.S,
            )
        if count != 1:
            raise RuntimeError(f"{path}: rate card insertion marker not found")
    text = text.replace(
        "<thead><tr><th>順位</th><th>場R</th><th>万舟率</th><th>結果</th><th>買い方1</th><th>頭・軸・消し</th><th>単発ROI</th></tr></thead>",
        "<thead><tr><th>順位</th><th>場R</th><th>万舟率</th><th>結果</th><th>買い方1</th><th>単発回収率</th></tr></thead>",
    )
    text = text.replace(
        "<thead><tr><th>順位</th><th>場R</th><th>万舟率</th><th>結果</th><th>買い方1</th><th>単発ROI</th></tr></thead>",
        "<thead><tr><th>順位</th><th>場R</th><th>万舟率</th><th>結果</th><th>買い方1</th><th>単発回収率</th></tr></thead>",
    )
    text = re.sub(r"\n?\.rate-roles\{[^}]+\}", "", text)
    text = re.sub(r"\n?\.rate-roles b\{[^}]+\}", "", text)

    for card_id in [
        "top5-x-card",
        "top5-x-result-card",
        "top10-note-card",
        "top10-note-result-card",
    ]:
        text = re.sub(
            r'\n?<div class="card (?:xpost|notepost) post-card" id="' + re.escape(card_id) + r'">.*?</div>\n?',
            "\n",
            text,
            count=1,
            flags=re.S,
        )
    text, count = re.subn(
        r'(<p class="muted">的中・回収率は「買い方1（検証用9点）」.*?</p>\s*</div>\n)',
        r"\1" + POST_CARDS + "\n",
        text,
        count=1,
        flags=re.S,
    )
    if count != 1:
        raise RuntimeError(f"{path}: post card insertion marker not found")

    if "var ROLE_RESULT_MAP={};" not in text:
        text, count = re.subn(
            r'(var RDATE="[^"]+", MAN=10000;\n)',
            r"\1var ROLE_RESULT_MAP={};\n",
            text,
            count=1,
        )
        if count != 1:
            raise RuntimeError(f"{path}: RDATE marker not found")

    text = text.replace(
        "トップ5の結果・的中・回収率を短文で投稿できます。",
        "トップ5の観察メモを短文で投稿できます。買い目や回収率は載せません。",
    )
    text = text.replace(
        "トップ10の結果・根拠・回収率をそのままnoteへ貼れる形式です。",
        "トップ10の観察メモと答え合わせをnoteへ貼れる形式です。買い目や回収率は載せません。",
    )
    text = text.replace(
        "万舟率トップ10（結果・的中・回収率つき）",
        "万舟率トップ10（結果つき）",
    )

    if "function roleDataUrl()" not in text:
        marker = "function acc(tr){"
        if marker not in text:
            raise RuntimeError(f"{path}: JS insertion marker not found")
        text = text.replace(marker, ROLE_JS + "\n" + marker, 1)
    elif (
        "function buildTopPosts(" not in text
        or "function renderRateTop10(" not in text
        or "function pickDetailsHtml(" not in text
        or "toggleRatePick(" not in text
        or "var ROLE_RANKING_DATA=null;" not in text
        or "top5-x-rank-post" not in text
        or "top10-note-result-post" not in text
        or "function boatLine(" in text
        or "function roleBox(" in text
        or "function rateRolesHtml(" in text
        or "function roleStrategyHtml(" in text
        or "function updateRoleResults(" in text
        or "ticketsHtml" in text
        or "role-tickets" in text
        or "検証用フォーメーション" in text
        or "買い方1=9点検証" in text
        or "確定分ROI" in text
        or "回収率をそのままnote" in text
        or "rateRolesHtml(r)" in text
        or "L.push('- 買い目:" in text
    ):
        text, count = re.subn(
            r"(?:var ROLE_RANKING_DATA=null;\n)?function esc\(s\)\{.*?\nfunction acc\(tr\)\{",
            ROLE_JS + "\nfunction acc(tr){",
            text,
            count=1,
            flags=re.S,
        )
        if count != 1:
            text, count = re.subn(
                r"function esc\(s\)\{.*?\nasync function loadResults\(\)\{",
                ROLE_JS + "\nasync function loadResults(){",
                text,
                count=1,
                flags=re.S,
            )
        if count != 1:
            raise RuntimeError(f"{path}: existing role JS replacement marker not found")

    text = re.sub(r"\n?\.role-tickets\{[^}]+\}", "", text)
    text = text.replace("  updateRoleResults();\n", "")

    if "ROLE_RESULT_MAP=map;" not in text:
        marker = "  var done=0,man=0,total=0,pend=0;"
        text = text.replace(marker, "  ROLE_RESULT_MAP=map;\n  updateRateResults();\n" + marker, 1)
    elif "updateRateResults();" not in text:
        text = text.replace("  ROLE_RESULT_MAP=map;\n", "  ROLE_RESULT_MAP=map;\n  updateRateResults();\n", 1)

    if "loadRoleRanking()" not in text.split("document.addEventListener('DOMContentLoaded'", 1)[-1]:
        if "showLen('xrank'); loadTimes();" in text:
            marker = "showLen('xrank'); loadTimes();"
            text = text.replace(marker, "showLen('xrank'); loadRoleRanking(); loadTimes();", 1)
        else:
            marker = "showLen('xrank');"
            text = text.replace(marker, "showLen('xrank'); loadRoleRanking();", 1)
    if "loadResults()" not in text.split("document.addEventListener('DOMContentLoaded'", 1)[-1]:
        text = text.replace("loadRoleRanking();", "loadRoleRanking(); loadResults();", 1)

    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="HTML files to patch. Defaults to manshu.html and manshu/*.html")
    return parser


def run(args: argparse.Namespace) -> int:
    root = Path.cwd()
    targets = [Path(path) for path in args.paths] if args.paths else default_targets(root)
    changed = []
    for target in targets:
        if patch_html(target):
            changed.append(str(target))
    if changed:
        print("patched manshu widgets:")
        for path in changed:
            print(f"- {path}")
    else:
        print("manshu widgets already present")
    return 0


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
