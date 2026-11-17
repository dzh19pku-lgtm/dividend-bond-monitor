import {formatNumber as fmt,validateManifest,validateSeries,expectedDate,selectRange,decisionText} from './data-utils.mjs';
const $=id=>document.getElementById(id);
let manifest, selected='000922', range='all', rows=[], loadId=0;
const numberIds={spread:'spread_pp',dividend:'dividend_percent',bond:'bond_percent',percentile:'percentile_expanding',zscore:'zscore_252',position:'range_position','mean-252':'mean_252','std-252':'std_252','mean-756':'mean_756','std-756':'std_756'};
function timeText(value){return value?new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'未知 / NA';}
async function readJSON(path){const response=await fetch(path,{cache:'no-store'});if(!response.ok) throw new Error(`数据读取失败（HTTP ${response.status}）`);return response.json();}
function clearMetrics(){for(const id of Object.keys(numberIds)) $(id).textContent='NA';$('data-date').textContent='暂无共同数据';$('export').setAttribute('aria-disabled','true');$('decision').textContent='数据未加载';}
function showError(error){clearMetrics();$('error').hidden=false;$('error').textContent=`${error.message}。请通过本地 HTTP 服务打开网站，并运行 python -m monitor build 生成数据。`;$('header-status').textContent='读取失败';$('header-status').className='badge warning';for(const id of ['yield-chart','spread-chart']) $(id).replaceChildren();}
function updateState(){
  if(!manifest) return;
  const item=manifest.indexes.find(i=>i.code===selected), current=item?.latest, expected=expectedDate(manifest.calendar);
  if(!item) return;
  const isCurrent=expected && current?.trade_date===expected;
  $('header-status').textContent=isCurrent?'已匹配最近收盘日':'数据待更新';$('header-status').className=`badge ${isCurrent?'':'warning'}`;
  $('quality').className=`notice ${isCurrent&&!item.missing_dates.length?'good':''}`;
  const runBad=['degraded','error','not_run'].includes(manifest.run.state);
  $('quality').textContent=!expected?'交易日历超出已核验年份，无法判断最新交易日。':!isCurrent?`应更新至 ${expected}；最新共同日期 ${current?.trade_date??'NA'}。股息率 ${item.dividend_latest_date??'NA'} / 国债 ${item.bond_latest_date??'NA'}，未对缺失日期进行填充。`:`同日匹配 ${expected} · ${item.matched_rows} 个共同观测日。${item.missing_dates.length?`历史缺失 ${item.missing_dates.length} 日（${item.missing_dates.slice(0,3).join('、')}），图中保留断点。`:''}${runBad?'最近采集存在失败，请查看来源详情。':'股息率采用官方 D/P2 替代口径；历史发布时间未知。'}`;
  $('decision').textContent=decisionText(current,expected);
}
async function selectIndex(code){
  const ticket=++loadId;selected=code;clearMetrics();$('error').hidden=true;
  for(const button of document.querySelectorAll('#index-nav button')){button.classList.toggle('active',button.dataset.code===code);button.setAttribute('aria-pressed',button.dataset.code===code);}
  try{
    const data=validateSeries(await readJSON(`data/${code}.json`));if(ticket!==loadId)return;
    if(data.code!==code)throw new Error('指数代码与文件不一致');
    rows=data.rows;const item=manifest.indexes.find(i=>i.code===code),current=item.latest;
    $('selected-code').textContent=code;$('selected-name').textContent=item.name;
    for(const [id,key] of Object.entries(numberIds))$(id).textContent=fmt(current?.[key],id==='percentile'||id==='position'?1:2);
    $('data-date').textContent=current?.trade_date??'无共同观测';$('sample-count').textContent=`${item.matched_rows} 个共同观测日`;
    $('percentile-note').textContent=item.matched_rows<252?`样本不足 252 日 · 当前 ${item.matched_rows} 日`:'截至当前的扩展样本分位（含当前值）';
    $('available-time').textContent=timeText(current?.available_at);$('trade-open').textContent=timeText(current?.earliest_trade_open);
    $('updated-time').textContent=timeText(manifest.run.finished_at);$('build-time').textContent=`构建于 ${timeText(manifest.generated_at)}`;
    $('signal').textContent=current?.zscore_252==null?'完整历史样本不足，暂不判断高低位或偏离程度。':`利差位于已观测历史的 ${fmt(current.percentile_expanding,1)}% 分位；252 日 Z-score 为 ${fmt(current.zscore_252)}。这不是买卖建议。`;
    $('export').href=`data/${code}.csv`;$('export').download=`${code}-dividend-bond.csv`;$('export').setAttribute('aria-disabled','false');
    const stateNames={current:'已更新',degraded:'部分数据异常',error:'采集失败',not_run:'尚未采集',stale_or_quarantined:'过期或异常值待核验',skipped_non_session_or_before_close:'非交易日或未收盘，正常跳过',historical_as_of:'历史时点快照'};
    const sourceLines=Object.entries(manifest.run.sources??{}).map(([id,s])=>`${id==='chinabond_cgb_10y'?'中债国债':manifest.indexes.find(i=>id.includes(i.code))?.name??id}：${stateNames[s.state]??s.state}${s.latest_date?' / '+s.latest_date:''}${s.error?' / '+s.error:''}`);
    $('source-details').textContent=`股息率：${manifest.dividend_label}\n国债：${manifest.bond_label}\n股息率最新归属日：${item.dividend_latest_date??'NA'}\n国债最新归属日：${item.bond_latest_date??'NA'}\n缺失日期：${item.missing_dates.join('、')||'当前区间无缺失'}\n本轮采集状态：${stateNames[manifest.run.state]??manifest.run.state}\n${sourceLines.join('\n')}\n${manifest.warnings.join('\n')}\n来源：oss-ch.csindex.com.cn / yield.chinabond.com.cn\n统计：1年=252、3年=756 个完整交易日；分位至少252个有效观测。CSV 为最新修订快照；严格按时点导出请使用 build --as-of。`;
    updateState();renderCharts();
  }catch(error){if(ticket===loadId)showError(error);}
}
const NS='http://www.w3.org/2000/svg';
function svgNode(name,attrs={},text){const el=document.createElementNS(NS,name);for(const [key,val] of Object.entries(attrs))el.setAttribute(key,val);if(text!==undefined)el.textContent=text;return el;}
function chart(id, data, series, height){
  const svg=$(id);svg.replaceChildren();const tooltip=svg.parentElement.querySelector('.tooltip');tooltip.hidden=true;
  const width=1000,left=48,right=20,top=24,bottom=30, plotH=height-top-bottom;
  const values=data.flatMap(r=>series.map(s=>r[s.key])).filter(v=>v!==null&&v!==undefined);
  if(!values.length){svg.append(svgNode('text',{x:500,y:height/2,'text-anchor':'middle'},'暂无可展示数据 · 缺失不会填充'));return;}
  let lo=Math.min(...values),hi=Math.max(...values);if(id==='spread-chart'){lo=Math.min(0,lo);hi=Math.max(0,hi);}
  const padding=Math.max((hi-lo)*.18,.10);lo-=padding;hi+=padding;
  const dates=data.map(r=>Date.parse(r.trade_date+'T00:00:00Z'));const start=dates[0],stop=dates.at(-1);
  const x=i=>left+(dates[i]-start)/Math.max(stop-start,86400000)*(width-left-right),y=v=>top+(hi-v)/(hi-lo)*plotH;
  for(let t=0;t<=4;t++){const val=lo+(hi-lo)*t/4,yy=y(val);svg.append(svgNode('line',{x1:left,x2:width-right,y1:yy,y2:yy,class:'grid-line'}),svgNode('text',{x:left-10,y:yy+3,'text-anchor':'end'},val.toFixed(2)));}
  if(lo<0&&hi>0)svg.append(svgNode('line',{x1:left,x2:width-right,y1:y(0),y2:y(0),class:'zero-line'}));
  const indexes=[...new Set([0,Math.floor(data.length/4),Math.floor(data.length/2),Math.floor(data.length*3/4),data.length-1])];
  for(const i of indexes)svg.append(svgNode('text',{x:x(i),y:height-8,'text-anchor':i===0?'start':i===data.length-1?'end':'middle'},data[i].trade_date));
  for(const s of series){let path='',connected=false;data.forEach((r,i)=>{const value=r[s.key];if(value==null){connected=false;return;}path+=`${connected?'L':'M'}${x(i).toFixed(2)},${y(value).toFixed(2)} `;connected=true;});svg.append(svgNode('path',{d:path,class:'series-line',stroke:s.color}));if(data.length===1&&data[0][s.key]!=null)svg.append(svgNode('circle',{cx:x(0),cy:y(data[0][s.key]),r:3,fill:s.color}));}
  const cross=svgNode('line',{x1:left,x2:left,y1:top,y2:height-bottom,stroke:'#718499','stroke-dasharray':'3 4',visibility:'hidden'});svg.append(cross);
  let active=0;
  function show(i){active=i;cross.setAttribute('x1',x(i));cross.setAttribute('x2',x(i));cross.setAttribute('visibility','visible');tooltip.textContent=data[i].trade_date+'\n'+series.map(s=>`${s.label}  ${fmt(data[i][s.key])} ${id==='spread-chart'?'百分点':'%'}`).join('\n');tooltip.hidden=false;tooltip.style.left=`${Math.min(70,Math.max(3,x(i)/width*100-8))}%`;}
  svg.onpointermove=event=>{const box=svg.getBoundingClientRect(),point=(event.clientX-box.left)/box.width*width;let nearest=0;for(let i=1;i<data.length;i++)if(Math.abs(x(i)-point)<Math.abs(x(nearest)-point))nearest=i;show(nearest);};
  svg.onpointerleave=()=>{tooltip.hidden=true;cross.setAttribute('visibility','hidden');};
  svg.onkeydown=event=>{if(['ArrowLeft','ArrowRight'].includes(event.key)){event.preventDefault();show(Math.max(0,Math.min(data.length-1,active+(event.key==='ArrowRight'?1:-1))));}};
}
function renderCharts(){const data=selectRange(rows,range);$('coverage').textContent=data.length?`${data[0].trade_date} — ${data.at(-1).trade_date} · ${data.filter(r=>r.spread_pp!==null).length} 个共同观测日（实际可用样本）`:'尚未积累历史';chart('yield-chart',data,[{key:'dividend_percent',label:'股息率 D/P2',color:'#62d6c3'},{key:'bond_percent',label:'10年国债',color:'#d7b47b'}],285);chart('spread-chart',data,[{key:'spread_pp',label:'股债收益差',color:'#86a9ed'}],190);}
async function load(){try{manifest=validateManifest(await readJSON('data/manifest.json'));$('index-nav').replaceChildren();for(const item of manifest.indexes){const button=document.createElement('button');button.dataset.code=item.code;button.append(document.createTextNode(item.name));const code=document.createElement('span');code.textContent=item.code;button.append(code);button.onclick=()=>selectIndex(item.code);$('index-nav').append(button);}await selectIndex(selected);}catch(error){showError(error);}}
$('refresh').onclick=load;
for(const button of document.querySelectorAll('#range-buttons button'))button.onclick=()=>{range=button.dataset.years;for(const other of document.querySelectorAll('#range-buttons button'))other.classList.toggle('active',other===button);renderCharts();};
setInterval(updateState,60000);
load();
