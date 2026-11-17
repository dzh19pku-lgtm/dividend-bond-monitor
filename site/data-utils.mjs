export function formatNumber(value, digits=2) {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : 'NA';
}
export function validateManifest(value) {
  if (value?.schema_version !== 1 || value.unit !== 'percent' || !Array.isArray(value.indexes) || !value.calendar?.years) throw new Error('数据清单格式不兼容，请重新构建');
  return value;
}
export function validateSeries(value) {
  if(value?.schema_version !== 1 || !/^\d{6}$/.test(value.code) || !Array.isArray(value.rows)) throw new Error('历史数据格式错误');
  let previous='';
  for(const row of value.rows){
    if(!/^\d{4}-\d{2}-\d{2}$/.test(row.trade_date) || row.trade_date<=previous) throw new Error('历史数据日期重复或无序');
    previous=row.trade_date;
    for(const key of ['dividend_percent','bond_percent','spread_pp']) if(row[key]!==null && (typeof row[key]!=='number'||!Number.isFinite(row[key]))) throw new Error('历史数据包含非法数值');
    if(row.spread_pp!==null && (row.dividend_percent===null||row.bond_percent===null||Math.abs(row.dividend_percent-row.bond_percent-row.spread_pp)>1e-6)) throw new Error('股债差与两项收益率不一致');
  }
  return value;
}
export function expectedDate(calendar, now=new Date()){
  const china = new Date(now.getTime()+8*3600000);
  let day = new Date(Date.UTC(china.getUTCFullYear(),china.getUTCMonth(),china.getUTCDate()));
  if(china.getUTCHours()<15) day.setUTCDate(day.getUTCDate()-1);
  for(let i=0;i<370;i++){
    const iso=day.toISOString().slice(0,10), spec=calendar.years[iso.slice(0,4)];
    if(!spec) return null;
    const open = spec.sessions ? spec.sessions.includes(iso) : day.getUTCDay()!==0 && day.getUTCDay()!==6 && !spec.closures.some(([a,b])=>a<=iso&&iso<=b);
    if(open) return iso;
    day.setUTCDate(day.getUTCDate()-1);
  }
  return null;
}
export function selectRange(rows, years){
  if(years==='all'||!rows.length) return rows;
  const date=new Date(rows.at(-1).trade_date+'T00:00:00Z');
  date.setUTCFullYear(date.getUTCFullYear()-Number(years));
  return rows.filter(r=>r.trade_date>=date.toISOString().slice(0,10));
}
export function decisionText(latest, expected, now=new Date()){
  if(!expected) return '交易日历待核验';
  if(!latest || latest.trade_date!==expected) return '等待同日数据补齐';
  if(!latest.tplus1_ready) return '回补或迟到数据 · 不满足原定次日开盘';
  if(!latest.tplus1_open || now>=new Date(latest.tplus1_open)) return '原定开盘已过 · 等待新的收盘数据';
  return '数据时点条件已满足 · 仅供观察';
}
