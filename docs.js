const COMPANY_BY_TAX={"0545569000076":"ชนิษฐา ค้าไม้","0545565000748":"แสงตะวัน 2022","0545566000687":"วริศมหาเฮง"};
const COMPANY_BY_SHOP={"THJ2H8XL":"ชนิษฐา ค้าไม้","THJ2ES6G":"แสงตะวัน 2022"};
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
  let m=/((?:TRSPEMKP|RCSPXSPB)\d\d-\d{5}-\d\d)[\s\S]{0,80}?(\d{4}-\d{7})/.exec(T);
  d.docNo=m?m[1]+m[2]:((/(?:Invoice No\.|Credit Note|Invoice number|Credit note number|Receipt Number|Receipt number)\s*[:：]\s*([A-Z0-9]{10,})/.exec(T)||[])[1]||"");
  d.date="";
  if(m=/(?:Invoice Date|\bDate)\s*:\s*(\d{4})-(\d\d)-(\d\d)/.exec(T))d.date=iso(m[1],m[2],m[3]);
  else if(m=/\/ Date\s+(\d\d)\/(\d\d)\/(\d{4})/.exec(T))d.date=iso(m[3],m[2],m[1]);
  else if(m=/(?:Invoice date|Credit note date|Receipt date|Receipt Date)\s*[:：]\s*([A-Z][a-z]{2}) (\d{1,2}), (\d{4})/.exec(T))d.date=iso(m[3],MON[m[1]],m[2]);
  const taxes=[...T.matchAll(/Tax\s*(?:ID|Number)[^\d]{0,12}(\d{13})/g)].map(x=>x[1]).filter(x=>!x.startsWith("0105"));
  d.tax=taxes.length?taxes[taxes.length-1]:"";
  d.shop=(/\b(THJ[0-9A-Z]{5})\b/.exec(T)||/Username\s+(\S+)/.exec(T)||/Creator Username:\s*(\S+)/.exec(T)||[])[1]||"";
  d.company=COMPANY_BY_TAX[d.tax]||COMPANY_BY_SHOP[d.shop]||d.tax;
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
  const L=pages.flatMap(groupLines),shop=(/THJ[0-9A-Z]{5}/.exec(L.join("\n"))||[""])[0],rows=[];let total=null;
  const R=/^(\d{2})\/(\d{2})\/(\d{4})((?:\s+-?[\d,]+\.\d\d){6})/,Tt=/^[^\d\s-].*?((?:-?[\d,]+\.\d\d\s*){6})$/;
  L.forEach(l=>{
    let m=R.exec(l);
    if(m){const v=m[4].trim().split(/\s+/).map(NUMF);rows.push({date:iso(m[3],m[2],m[1]),shop,sales:v[0],fee:v[1],ship:v[2],mkt:v[3],claim:v[4],net:v[5]});}
    else if(m=Tt.exec(l))total=m[1].trim().split(/\s+/).map(NUMF);
  });
  return {shop,company:COMPANY_BY_SHOP[shop]||shop,rows,total};
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
  s.addRow(["บริษัท","ร้าน/ผู้ใช้","ผู้ออกเอกสาร","ประเภท","เลขที่เอกสาร","วันที่","เดือน","อ้างอิงเอกสารเดิม","ก่อน VAT","VAT","รวม VAT","หัก ณ ที่จ่าย %","ยอดหัก ณ ที่จ่าย","ยอดจ่ายสุทธิ","ตรวจ VAT","ตรวจรายการย่อย","ไฟล์"]);
  l.addRow(["เลขที่เอกสาร","วันที่","บริษัท","รายการ","ก่อน VAT","VAT","รวม VAT"]);
  docs.forEach((d,i)=>{
    const n=i+2;
    s.addRow([d.company,d.shop,d.vendor,d.type,d.docNo,D(d.date),d.date.slice(0,7),d.ref,d.ex,d.vat,d.inc,d.whtRate,d.wht,
      {formula:`K${n}-M${n}`,result:d.net},{formula:`IF(ROUND(I${n}+J${n}-K${n},2)=0,"OK","CHECK")`,result:d.okVat?"OK":"CHECK"},
      {formula:`IF(ROUND(SUMIFS('รายการย่อย'!E:E,'รายการย่อย'!A:A,E${n})-I${n},2)=0,"OK","CHECK")`,result:d.okLines?"OK":"CHECK"},d.file]);
    d.lines.forEach(x=>l.addRow([d.docNo,D(d.date),d.company,x.desc,x.ex,x.vat==null?null:x.vat,x.inc==null?null:x.inc]));
  });
  styleSheet(s,[18,20,12,18,34,12,10,34,14,12,14,10,14,14,10,14,40],[9,10,11,13,14],[6]);
  styleSheet(l,[34,12,18,40,14,12,14],[5,6,7],[2]);
  s.autoFilter={from:"A1",to:"Q"+(docs.length+1)};
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
