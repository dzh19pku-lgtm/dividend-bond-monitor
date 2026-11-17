import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {expectedDate,validateManifest,validateSeries,formatNumber,selectRange,decisionText} from '../site/data-utils.mjs';
const calendar=JSON.parse(readFileSync(new URL('../data/calendar.json',import.meta.url),'utf8'));
test('实时过期检测：盘前、盘后、休市与未知年份',()=>{
  assert.equal(expectedDate(calendar,new Date('2026-11-17T10:00:00+08:00')),'2026-11-16');
  assert.equal(expectedDate(calendar,new Date('2026-11-17T20:00:00+08:00')),'2026-11-17');
  assert.equal(expectedDate(calendar,new Date('2026-10-10T20:00:00+08:00')),'2026-10-09');
  assert.equal(expectedDate(calendar,new Date('2099-01-05T20:00:00+08:00')),null);
});
test('前端拒绝单位错误、重复日期和虚构利差',()=>{
  assert.throws(()=>validateManifest({schema_version:1,unit:'fraction',indexes:[]}));
  const row={trade_date:'2026-11-16',dividend_percent:4,bond_percent:1.6,spread_pp:2.4};
  assert.equal(validateSeries({schema_version:1,code:'000922',rows:[row]}).rows.length,1);
  assert.throws(()=>validateSeries({schema_version:1,code:'000922',rows:[row,row]}));
  assert.throws(()=>validateSeries({schema_version:1,code:'000922',rows:[{...row,spread_pp:3}]}));
});
test('样本范围不填充历史；缺失数值显示 NA',()=>{
  const rows=[{trade_date:'2020-01-01'},{trade_date:'2026-11-16'}];
  assert.equal(selectRange(rows,'1').length,1);assert.equal(selectRange(rows,'all').length,2);
  assert.equal(formatNumber(null),'NA');assert.equal(formatNumber(0),'0.00');
});
test('迟到和过期数据不得显示为下一开盘已就绪',()=>{
  const row={trade_date:'2026-11-16',tplus1_ready:false,tplus1_open:'2026-11-17T09:30:00+08:00'};
  assert.match(decisionText(row,'2026-11-16'),/迟到/);
  assert.match(decisionText({...row,tplus1_ready:true},'2026-11-16',new Date('2026-11-17T10:00:00+08:00')),/已过/);
  assert.match(decisionText(row,'2026-11-17'),/等待/);
});
test('实际生成文件可被前端读取，CSV 与 JSON 同日同数',()=>{
  const manifest=validateManifest(JSON.parse(readFileSync(new URL('../site/data/manifest.json',import.meta.url),'utf8')));
  for(const item of manifest.indexes){
    const data=validateSeries(JSON.parse(readFileSync(new URL(`../site/data/${item.code}.json`,import.meta.url),'utf8')));
    const csv=readFileSync(new URL(`../site/data/${item.code}.csv`,import.meta.url),'utf8').trim().split('\n');
    assert.equal(csv.length,data.rows.length+1);
    assert.equal(item.code,data.code);
    assert.equal(data.rows.length,item.rows);
  }
});
