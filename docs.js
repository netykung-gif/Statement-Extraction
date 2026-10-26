// ตารางชื่อเรียกแบบย่อ (ไม่บังคับ) ถ้าไม่มีในตาราง ระบบจะใช้ชื่อที่อ่านได้จากเอกสารจริง
const ALIAS_BY_TAX={"0545569000076":"ชนิษฐา ค้าไม้","0545565000748":"แสงตะวัน 2022","0545566000687":"วริศมหาเฮง"};
const ALIAS_BY_SHOP={"THJ2H8XL":"ชนิษฐา ค้าไม้","THJ2ES6G":"แสงตะวัน 2022"};
const MON={Jan:1,Feb:2,Mar:3,Apr:4,May:5,Jun:6,Jul:7,Aug:8,Sep:9,Oct:10,Nov:11,Dec:12};
const NUMF=s=>parseFloat(String(s).replace(/[฿,\s]/g,"").replace(/[−–]/g,"-"));
const r2=x=>Math.round(x*100)/100;
const iso=(y,m,d)=>y+"-"+String(m).padStart(2,"0")+"-"+String(d).padStart(2,"0");
const AM="([\\d,]+\\.\\d\\d)";
const RX={
  ex:[new RegExp("^Total\\s+"+AM,"m"),new RegExp("after discount\\s+"+AM),new RegExp("(?:Subtotal \\(excluding VAT\\)|Different amount \\(excluding VAT\\))\\s*฿\\s*"+AM)],
  vat:[new RegExp("7% \\(VAT\\)\\s+"+AM),new RegExp("VAT 7%\\s+"+AM),new RegExp("Total VAT 7%\\s*฿\\s*"+AM)],
  inc:[new RegExp("Total \\(Including Tax\\)\\s+"+AM),new RegExp("\\(Included VAT\\)\\s+"+AM),new RegExp("including VAT\\s*[）)]\\s*฿\\s*"+AM),new RegExp("Net Total Shipping Fee\\s+"+AM),new RegExp("Total [Aa]mount\\s+"+AM),new RegExp("Total Amount\\s*฿\\s*"+AM)]
};
function firstNum(list,T){for(const r of list){const m=r.exec(T);if(m)return NUMF(m[1]);}return null;}

function parseDoc(pages){
  const L=pages.flatMap(groupLines),T=L.join("\n"),J=L.join(" "),t=r=>r.test(T),d={};
  d.vendor=t(/SPX Express/)?"SPX":t(/Shopee \(Thailand\)/)?"Shopee":t(/Lazada (Express )?Limited/)?"Lazada":t(/TikTok Shop|Thai Happy|Creator name/)?"TikTok":"";
  const sign=t(/^CREDIT NOTE$/m)?-1:1;
  d.type=sign<0?"ใบลดหนี้":"ใบกำกับภาษี/ใบเสร็จ";
  let m=/([A-Z]{5,12}\d\d-\d{5}-\d\d)[\s\S]{0,80}?(\d{4}-\d{7})/.exec(T);
  d.docNo=m?m[1]+m[2]:((/(?:Invoice No\.|Credit Note|Invoice number|Credit note number|Receipt Number|Receipt number)\s*[:：]\s*([A-Z0-9]{10,})/.exec(T)||[])[1]||"");
  d.date="";
  if(m=/(?:Invoice Date|\bDate)\s*:\s*(\d{4})-(\d\d)-(\d\d)/.exec(T))d.date=iso(m[1],m[2],m[3]);
  else if(m=/\/ Date\s+(\d\d)\/(\d\d)\/(\d{4})/.exec(T))d.date=iso(m[3],m[2],m[1]);
  else if(m=/(?:Invoice date|Credit note date|Receipt date|Receipt Date)\s*[:：]\s*([A-Z][a-z]{2}) (\d{1,2}), (\d{4})/.exec(T))d.date=iso(m[3],MON[m[1]],m[2]);
  const taxes=[...T.matchAll(/Tax\s*(?:ID|Number)[^\d]{0,12}(\d{13})/g)].map(x=>x[1]).filter(x=>!x.startsWith("0105"));
  d.tax=taxes.length?taxes[taxes.length-1]:"";
  d.shop=(/\b(THJ[0-9A-Z]{5})\b/.exec(T)||/Username\s+(\S+)/.exec(T)||/Creator Username:\s*(\S+)/.exec(T)||[])[1]||"";
  const cl=x=>x.replace(/\(Head Office\)|\(สนง\.ใหญ่\)/g,"").replace(/\s+/g," ").trim();
  let name=(/Customer name\s+(.+?)\s+เลขที่\/ No\./.exec(T)||/THJ[0-9A-Z]{5}[^\n]*\n(.+?)\s+(?:Invoice Date|Date)\s*:/.exec(T)||[])[1]||"";
  if(!name){const all=[...T.matchAll(/(?:Client Name|Merchant Name)\s*[:：]\s*(.+)$/gm)];if(all.length)name=all[all.length-1][1];}
  d.name=cl(name);
  d.company=ALIAS_BY_TAX[d.tax]||ALIAS_BY_SHOP[d.shop]||d.name||d.tax;
  d.ref=((/Number#\s*(TH\w+)/.exec(T)||/Original invoice number\s*[:：]\s*(\S+)/.exec(T)||[])[1])||"";
  let ex=firstNum(RX.ex,T),vat=firstNum(RX.vat,T),inc=firstNum(RX.inc,T);
  if(ex==null)ex=inc;if(inc==null)inc=ex;if(vat==null)vat=0;
  const wr=/(?:ร้อยละ|rate of|deducted)\s*(\d+(?:\.\d+)?)/.exec(J);
  const wa=/(?:เป็นจำนวนเงิน|เป็นจำนวน|amounting to|payer at)\s*฿?\s*([\d,]+\.\d\d)/.exec(J)||/([\d,]+\.\d\d)\s*บาท\s*แทน/.exec(J);
  d.whtRate=wr?+wr[1]:0;d.wht=wa?sign*NUMF(wa[1]):0;
  d.lines=[];
  L.forEach(l=>{
    let x;
    if(x=/^-\s*([A-Za-z].*?)\s+฿\s*([\d,]+\.\d\d)\s+฿\s*([\d,]+\.\d\d)\s+฿\s*([\d,]+\.\d\d)$/.exec(l))d.lines.push({desc:x[1],ex:sign*NUMF(x[2]),vat:sign*NUMF(x[3]),inc:sign*NUMF(x[4])});
    else if(x=/^-\s*([A-Za-z].*?)\s*\/\s*฿\s*([\d,]+\.\d\d)$/.exec(l))d.lines.push({desc:x[1],ex:sign*NUMF(x[2]),vat:0,inc:sign*NUMF(x[2])});
    else if(x=/^(\d{1,2})\s+([A-Za-z].*?)\s+\d+\s+[\d,]+\.\d\d\s+([\d,]+\.\d\d)$/.exec(l)||/^(\d{1,2})\s+([A-Za-z].*?)\s+([\d,]+\.\d\d)$/.exec(l))d.lines.push({desc:x[2],ex:sign*NUMF(x[3])});
  });
  d.ex=sign*ex;d.vat=sign*vat;d.inc=sign*inc;
  d.net=r2(d.inc-d.wht);
  d.okVat=Math.abs(d.ex+d.vat-d.inc)<0.015;
  d.okLines=d.lines.length>0&&Math.abs(d.lines.reduce((s,x)=>s+x.ex,0)-d.ex)<0.015;
  return d;
}

function parseLzdIncome(pages){
  const L=pages.flatMap(groupLines),shop=(/THJ[0-9A-Z]{5}/.exec(L.join("\n"))||[""])[0],rows=[];
  const sl=L.find(l=>/THJ[0-9A-Z]{5}/.test(l)&&l.includes("รหัส"));const shopName=sl?sl.slice(0,sl.indexOf("รหัส")).trim():"";let total=null;
  const R=/^(\d{2})\/(\d{2})\/(\d{4})((?:\s+-?[\d,]+\.\d\d){6})/,Tt=/^[^\d\s-].*?((?:-?[\d,]+\.\d\d\s*){6})$/;
  L.forEach(l=>{
    let m=R.exec(l);
    if(m){const v=m[4].trim().split(/\s+/).map(NUMF);rows.push({date:iso(m[3],m[2],m[1]),shop,sales:v[0],fee:v[1],ship:v[2],mkt:v[3],claim:v[4],net:v[5]});}
    else if(m=Tt.exec(l))total=m[1].trim().split(/\s+/).map(NUMF);
  });
  return {shop,shopName,company:ALIAS_BY_SHOP[shop]||shopName||shop,rows,total};
}

async function saveWb(wb,name){
  const buf=await wb.xlsx.writeBuffer(),a=document.createElement("a");
  a.href=URL.createObjectURL(new Blob([buf],{type:"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}));
  a.download=name;a.click();URL.revokeObjectURL(a.href);
}
function styleSheet(ws,widths,numCols,dateCols){
  ws.columns=widths.map(w=>({width:w}));
  ws.getRow(1).eachCell(c=>{c.font={name:"Arial",bold:true,color:{argb:"FFFFFFFF"}};c.fill={type:"pattern",pattern:"solid",fgColor:{argb:"FF1F4E78"}};c.alignment={horizontal:"center",vertical:"middle",wrapText:true};});
  ws.eachRow((r,i)=>{if(i>1){r.eachCell({includeEmpty:true},(c,j)=>{c.font={name:"Arial",size:10};if(numCols.includes(j))c.numFmt="#,##0.00";if(dateCols.includes(j))c.numFmt="dd/mm/yyyy";});}});
  ws.views=[{state:"frozen",ySplit:1}];
}
const D=s=>s?new Date(s+"T00:00:00Z"):null;

function buildDocsWorkbook(docs){
  const wb=new ExcelJS.Workbook(),s=wb.addWorksheet("สรุปเอกสาร"),l=wb.addWorksheet("รายการย่อย");
  s.addRow(["บริษัท","ร้าน/ผู้ใช้","ผู้ออกเอกสาร","ประเภท","เลขที่เอกสาร","วันที่","เดือน","อ้างอิงเอกสารเดิม","ก่อน VAT","VAT","รวม VAT","หัก ณ ที่จ่าย %","ยอดหัก ณ ที่จ่าย","ยอดจ่ายสุทธิ","ตรวจ VAT","ตรวจรายการย่อย","ไฟล์","เลขผู้เสียภาษีลูกค้า"]);
  l.addRow(["เลขที่เอกสาร","วันที่","บริษัท","รายการ","ก่อน VAT","VAT","รวม VAT"]);
  docs.forEach((d,i)=>{
    const n=i+2;
    s.addRow([d.company,d.shop,d.vendor,d.type,d.docNo,D(d.date),d.date.slice(0,7),d.ref,d.ex,d.vat,d.inc,d.whtRate,d.wht,
      {formula:`K${n}-M${n}`,result:d.net},{formula:`IF(ROUND(I${n}+J${n}-K${n},2)=0,"OK","CHECK")`,result:d.okVat?"OK":"CHECK"},
      {formula:`IF(ROUND(SUMIFS('รายการย่อย'!E:E,'รายการย่อย'!A:A,E${n})-I${n},2)=0,"OK","CHECK")`,result:d.okLines?"OK":"CHECK"},d.file,d.tax]);
    d.lines.forEach(x=>l.addRow([d.docNo,D(d.date),d.company,x.desc,x.ex,x.vat==null?null:x.vat,x.inc==null?null:x.inc]));
  });
  styleSheet(s,[18,20,12,18,34,12,10,34,14,12,14,10,14,14,10,14,40,16],[9,10,11,13,14],[6]);
  styleSheet(l,[34,12,18,40,14,12,14],[5,6,7],[2]);
  s.autoFilter={from:"A1",to:"R"+(docs.length+1)};
  return wb;
}

function buildLzdWorkbook(res){
  const wb=new ExcelJS.Workbook(),ws=wb.addWorksheet("รายได้ Lazada");
  ws.addRow(["วันที่","รหัสร้าน","บริษัท","ยอดรายการขาย","ค่าธรรมเนียมจากลาซาด้า","ค่าบริการขนส่ง","ค่าธรรมเนียมด้านการตลาด","ค่าเคลม","จำนวนเงิน","ตรวจแถว"]);
  res.rows.forEach((r,i)=>{const n=i+2;ws.addRow([D(r.date),r.shop,res.company,r.sales,r.fee,r.ship,r.mkt,r.claim,r.net,{formula:`IF(ROUND(SUM(D${n}:H${n})-I${n},2)=0,"OK","CHECK")`,result:Math.abs(r.sales+r.fee+r.ship+r.mkt+r.claim-r.net)<0.015?"OK":"CHECK"}]);});
  const last=res.rows.length+1,sum=k=>r2(res.rows.reduce((s,r)=>s+r[k],0));
  ws.addRow([]);
  ws.addRow(["รวม (สูตร)","","",...["D","E","F","G","H","I"].map((c,j)=>({formula:`SUM(${c}2:${c}${last})`,result:sum(["sales","fee","ship","mkt","claim","net"][j])}))]);
  if(res.total)ws.addRow(["รวมตามรายงาน PDF","","",...res.total]);
  styleSheet(ws,[12,12,18,16,18,14,18,12,14,10],[4,5,6,7,8,9],[1]);
  return wb;
}

const ALIAS_BY_SELLER={"81918258":"ชนิษฐา ค้าไม้","194032020":"แสงตะวัน 2022"};
const PUA_MAP={"\uf70a":"\u0e48","\uf70b":"\u0e49","\uf70e":"\u0e4c"};
const fixThai=s=>{for(const k in PUA_MAP)s=s.split(k).join(PUA_MAP[k]);return s.replace(/\u0e4d\u0e32/g,"\u0e33");};
const skel=s=>fixThai(s).replace(/[\s\uf700-\uf71f]/g,"").replace(/[\u0e34-\u0e3a\u0e47-\u0e4e]/g,"");
const SK={price:skel("ราคาสินค้า"),refund:skel("คืนให้ผู้ซื้อ"),ship:skel("ชำระโดยผู้ซื้อ"),shipW:skel("จัดส่ง"),net:skel("จำนวนเงินที่โอนแล้วทั้งหมด")};

function clusterBy(vals,gap){
  const s=[...vals].sort((a,b)=>a-b),out=[];
  s.forEach(v=>{if(out.length&&v-out[out.length-1].max<=gap){const c=out[out.length-1];c.max=v;c.n++;}else out.push({min:v,max:v,n:1});});
  return out.map(c=>c.max);
}

function parseShopeeIncome(pages){
  const res={seller:"",rows:[],cols:null,adj:[],sum:{},warn:[]};
  let colR=null;
  pages.forEach((raw,pi)=>{
    const items=raw.map(i=>({s:fixThai(i.str.trim()),x:i.x,r:i.x+i.w,y:i.y})).filter(i=>i.s);
    const lines=groupLines(raw).map(fixThai);
    if(pi===0){
      lines.forEach(l=>{const m=/(?:^|\s)(\d{8,12})(\d{6})(?:\s|$)/.exec(l);if(m&&!res.seller)res.seller=m[1];const s=skel(l);
        if(!res.bank&&s.startsWith(skel("ชื่อในบัญชีธนาคาร"))&&l.includes(":"))res.bank=l.slice(l.indexOf(":")+1).trim();
        for(const k of ["price","refund","net"]){const n=k==="ship"?null:SK[k];if(n&&s.startsWith(n)&&res.sum[k]==null){const t=/฿?([\-−]?[\d,]+)$/.exec(s);if(t)res.sum[k]=NUMF(t[1]);}}
        if(s.startsWith(SK.shipW)&&s.includes(SK.ship)&&res.sum.ship==null){const t=/([\-−]?[\d,]+)$/.exec(s);if(t)res.sum.ship=NUMF(t[1]);}});
    }
    lines.forEach(l=>{const m=/^(\d{4}-\d\d-\d\d)\s+(.*[\u0e01-\u0e5b].*?)\s+([−-][\d,]+)$/.exec(l.trim());if(m)res.adj.push({date:m[1],desc:m[2],amt:NUMF(m[3])});});
    const anc=items.filter(i=>i.x<90&&/^\d{4}-\d\d(-\d\d)?$/.test(i.s)).sort((a,b)=>b.y-a.y);
    if(!anc.length)return;
    const labs=items.filter(i=>i.x<66&&/^(จำนวนเงิน|รายละเอียด)/.test(i.s.replace(/\s/g,"")));
    const bands=anc.map((a,i)=>({a,top:a.y+4,bot:Math.max(i+1<anc.length?anc[i+1].y+3:-1e9,Math.max(-1e9,...labs.filter(l=>l.y<a.y-3).map(l=>l.y))+1)}));
    const inBand=b=>items.filter(i=>i.y<=b.top&&i.y>b.bot);
    if(!colR){
      const nums=[];bands.forEach(b=>inBand(b).forEach(i=>{if(i.x>=66&&/^−?[\d,]+$/.test(i.s))nums.push(i.r);}));
      const rs=clusterBy(nums,6);
      const hd=items.filter(i=>i.x>=66&&i.y>anc[0].y+4&&i.y<anc[0].y+75).sort((a,b)=>b.y-a.y);
      const cells=[];
      hd.forEach(h=>{const c=(h.x+h.r)/2,f=cells.find(z=>Math.abs(z.c-c)<=10);if(f)f.t.push(h.s);else cells.push({c,t:[h.s]});});
      colR=rs.map(r=>{const cell=cells.find(z=>z.c<=r+3&&r-z.c<=75&&!z.used&&rs.filter(q=>q>=z.c-3).sort((a,b)=>a-b)[0]===r);if(cell)cell.used=true;return {r,label:cell?cell.t.join(" "):"คอลัมน์"};});
      res.cols=colR.map(c=>c.label);
    }
    if(!colR)return;
    bands.forEach(b=>{
      const its=inBand(b),dt=its.find(i=>i===b.a);
      let date=b.a.s+(its.filter(i=>i.x<90&&/^-\d\d$/.test(i.s)).map(i=>i.s)[0]||"");
      if(!/^\d{4}-\d\d-\d\d$/.test(date)||its.some(i=>i.x>=66&&i.x<520&&/[\u0e01-\u0e5b]/.test(i.s)))return;
      const v=colR.map(()=>"");
      its.filter(i=>i.x>=66&&/^−?[\d,]+$/.test(i.s)).sort((a,b)=>b.y-a.y||a.x-b.x).forEach(i=>{
        let k=-1,best=7;colR.forEach((c,j)=>{const d=Math.abs(c.r-i.r);if(d<best){best=d;k=j;}});if(k>=0)v[k]+=i.s;});
      res.rows.push({date,v:v.map(x=>x===""?0:NUMF(x))});
    });
  });
  if(res.cols){
    const ix=n=>res.cols.findIndex(c=>skel(c).includes(n));
    res.ix={price:ix(SK.price),refund:ix(SK.refund),ship:res.cols.findIndex(c=>skel(c).includes(SK.ship)&&skel(c).includes(SK.shipW)),net:res.cols.length-1};
    const S=k=>res.ix[k]<0?0:res.rows.reduce((a,r)=>a+r.v[res.ix[k]],0);
    ["price","refund","ship","net"].forEach(k=>{if(res.sum[k]!=null&&Math.abs(S(k)-res.sum[k])>1)res.warn.push("ผลรวม "+k+" = "+S(k).toLocaleString()+" แต่รายงานสรุป "+res.sum[k].toLocaleString());});
    res.rows.forEach(r=>{const o=r.v.slice(0,-1).reduce((a,b)=>a+b,0);if(Math.abs(o-r.v[r.v.length-1])>1.01)res.warn.push("แถว "+r.date+" ผลรวมคอลัมน์ไม่เท่ายอดโอน");});
  }
  res.company=ALIAS_BY_SELLER[res.seller]||res.bank||res.seller;
  return res;
}

function buildShpWorkbook(list){
  const wb=new ExcelJS.Workbook(),sm=wb.addWorksheet("สรุป"),ad=wb.addWorksheet("รายการปรับปรุง");
  sm.addRow(["บริษัท","Seller ID","วันที่โอนเงิน","ราคาสินค้า","ยอดคืนเงิน","ค่าจัดส่งที่ชำระโดยผู้ซื้อ","ยอดโอนสุทธิ","ยอดตามสูตรเดิม (ราคา − |คืน| + ค่าจัดส่งผู้ซื้อ)"]);
  ad.addRow(["บริษัท","Seller ID","วันที่","รายการ","จำนวนเงิน"]);
  list.forEach(r=>{
    const ws=wb.addWorksheet("Shopee_"+(r.seller||(list.indexOf(r)+1))),L=i=>String.fromCharCode(66+i),n=r.cols.length,nl=L(n-1);
    ws.addRow(["วันที่โอนเงิน",...r.cols,"ตรวจยอด"]);
    r.rows.forEach((x,i)=>{const k=i+2,sumOthers=x.v.slice(0,-1).reduce((a,b)=>a+b,0);
      ws.addRow([D(x.date),...x.v,{formula:`IF(ROUND(SUM(B${k}:${L(n-2)}${k})-${nl}${k},2)=0,"OK","CHECK")`,result:Math.abs(sumOthers-x.v[n-1])<0.01?"OK":"CHECK"}]);
      const g=j=>j<0?0:x.v[j];
      sm.addRow([r.company,r.seller,D(x.date),g(r.ix.price),g(r.ix.refund),g(r.ix.ship),x.v[n-1],{formula:`D${sm.rowCount+1}-ABS(E${sm.rowCount+1})+F${sm.rowCount+1}`,result:g(r.ix.price)-Math.abs(g(r.ix.refund))+g(r.ix.ship)}]);
    });
    styleSheet(ws,[12,...r.cols.map(()=>16),10],r.cols.map((_,i)=>i+2),[1]);
    ws.getRow(1).height=48;
    r.adj.forEach(a=>ad.addRow([r.company,r.seller,D(a.date),a.desc,a.amt]));
  });
  styleSheet(sm,[18,14,12,14,14,20,14,26],[4,5,6,7,8],[3]);styleSheet(ad,[18,14,12,44,14],[5],[3]);
  return wb;
}
