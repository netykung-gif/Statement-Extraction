pdfjsLib.GlobalWorkerOptions.workerSrc="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";

const NUM="\\d{1,3}(?:,\\d{3})*\\.\\d{2}";
const ROW=new RegExp("^(\\d{2}/\\d{2}/\\d{2})\\s+(.+?)\\s+((?:"+NUM+"\\s+)+)(\\d{1,4})\\s*$");
const TYPE=/^(.*?\([A-Z]+\))\s*(.*)$/;
const TIME=/^(\d{2}:\d{2})\s*(.*)$/;

function groupLines(items){
  const rows=[];
  items.filter(i=>i.str.trim()!=="").sort((a,b)=>b.y-a.y||a.x-b.x).forEach(it=>{
    const r=rows.find(r=>Math.abs(r.y-it.y)<=3);
    if(r)r.items.push(it);else rows.push({y:it.y,items:[it]});
  });
  return rows.sort((a,b)=>b.y-a.y).map(r=>{
    r.items.sort((a,b)=>a.x-b.x);
    let s="",end=null;
    r.items.forEach(it=>{
      if(end!==null&&it.x-end>1.5)s+=" ";
      s+=it.str.trim();
      end=it.x+it.w;
    });
    return s.replace(/\s+/g," ").trim();
  });
}

function parseKrungthai(pages){
  const lines=pages.flatMap(groupLines);
  const rows=[];
  for(let i=0;i<lines.length;i++){
    const m=ROW.exec(lines[i]);
    if(!m)continue;
    const vals=m[3].trim().split(/\s+/).map(v=>Math.round(parseFloat(v.replace(/,/g,""))*100));
    const tm=TYPE.exec(m[2]);
    let time="",extra="";
    const t=TIME.exec(lines[i+1]||"");
    if(t){time=t[1];extra=t[2];i++;}
    rows.push({date:m[1],time,type:tm?tm[1]:m[2],details:((tm?tm[2]:"")+" "+extra).trim(),
      amount:vals.length>1?vals[vals.length-2]:0,balance:vals[vals.length-1],branch:parseInt(m[4],10)});
  }
  let prev=null,open=0;
  rows.forEach(r=>{
    if(prev===null){prev=r.type.includes("เข้า")?r.balance-r.amount:r.balance+r.amount;open=prev;}
    const d=r.balance-prev;
    r.wd=d<0?-d/100:null;
    r.dp=d>0?d/100:null;
    r.bal=r.balance/100;
    const [dd,mm,yy]=r.date.split("/").map(Number);
    r.jsDate=new Date(Date.UTC(yy+2500-543,mm-1,dd));
    prev=r.balance;
  });
  return {rows,opening:open/100};
}


const COLS={
  date:{h:"Date",w:12,fmt:"dd/mm/yyyy"},
  time:{h:"Time",w:8,fmt:"hh:mm"},
  type:{h:"Transaction Type",w:30},
  channel:{h:"Channel",w:22},
  details:{h:"Details / Ref",w:46},
  wd:{h:"Withdrawal (THB)",w:16,fmt:"#,##0.00",num:true},
  dp:{h:"Deposit (THB)",w:16,fmt:"#,##0.00",num:true},
  bal:{h:"Balance (THB)",w:18,fmt:"#,##0.00",num:true},
  branch:{h:"Branch",w:8}
};

const KBANK_NUM=/^\d{1,3}(?:,\d{3})*\.\d{2}$/;

function fillKbank(row,items){
  items.forEach(i=>{
    const s=i.s;
    if(/^\d{2}:\d{2}$/.test(s)&&i.x<125){row.time=s;return;}
    if(KBANK_NUM.test(s)){
      const v=Math.round(parseFloat(s.replace(/,/g,""))*100);
      if(i.x+i.w>290)row.bal=v;else row.amt=v;
      return;
    }
    if(i.x<225)row.type.push(s);
    else if(i.x<402)row.channel.push(s);
    else row.details.push(s);
  });
}

function parseKasikorn(pages){
  const all=[];
  pages.forEach(items=>{
    const its=items.filter(i=>i.str.trim()!==""&&i.x>=60).map(i=>({x:i.x,y:i.y,w:i.w,s:i.str.trim()}));
    const lines=[];
    its.sort((a,b)=>b.y-a.y||a.x-b.x).forEach(it=>{
      const l=lines.find(l=>Math.abs(l.y-it.y)<=2);
      if(l)l.items.push(it);else lines.push({y:it.y,items:[it]});
    });
    lines.sort((a,b)=>b.y-a.y);
    let cur=null,lastY=0;
    lines.forEach(l=>{
      l.items.sort((a,b)=>a.x-b.x);
      const d=l.items.find(i=>i.x<100&&/^\d{2}-\d{2}-\d{2}$/.test(i.s));
      if(d){
        cur={date:d.s,time:"",type:[],channel:[],details:[],amt:null,bal:null};
        all.push(cur);
        fillKbank(cur,l.items.filter(i=>i!==d));
        lastY=l.y;
      }else if(cur&&lastY-l.y<=14){
        fillKbank(cur,l.items);
        lastY=l.y;
      }else cur=null;
    });
  });
  let opening=null;
  const rows=[];
  all.forEach(r=>{
    const type=r.type.join(" ");
    if(type.includes("ยอดยกมา")){if(opening===null)opening=r.bal;return;}
    if(r.bal===null)return;
    rows.push({time:r.time,type,channel:r.channel.join(" "),details:r.details.join(" "),amount:r.amt,balance:r.bal,dateStr:r.date});
  });
  if(opening===null&&rows.length){const f=rows[0];opening=f.type.includes("รับ")||f.type.includes("ฝาก")?f.balance-f.amount:f.balance+f.amount;}
  let prev=opening;
  rows.forEach(r=>{
    const d=r.balance-prev;
    r.wd=d<0?-d/100:null;
    r.dp=d>0?d/100:null;
    r.bal=r.balance/100;
    const [dd,mm,yy]=r.dateStr.split("-").map(Number);
    r.jsDate=new Date(Date.UTC(2000+yy,mm-1,dd));
    prev=r.balance;
  });
  return {rows,opening:opening/100};
}

const PARSERS=[
  {name:"Krungthai Statement Extraction",parse:parseKrungthai,keys:["date","time","type","details","wd","dp","bal","branch"]},
  {name:"Kasikorn Statement Extraction",parse:parseKasikorn,keys:["date","time","type","channel","details","wd","dp","bal"]}
];
let current=0,data=[],opening=0,fileName="statement";

const $=id=>document.getElementById(id);
const fmt=n=>n==null?"":n.toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2});
const dstr=d=>String(d.getUTCDate()).padStart(2,"0")+"/"+String(d.getUTCMonth()+1).padStart(2,"0")+"/"+d.getUTCFullYear();
const esc=s=>String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;");

function buildMenu(){
  $("menu").innerHTML="";
  PARSERS.forEach((p,i)=>{
    const b=document.createElement("button");
    b.textContent=p.name;
    b.className=i===current?"on":"";
    b.onclick=()=>{current=i;buildMenu();reset();};
    $("menu").appendChild(b);
  });
  $("title").textContent=PARSERS[current].name;
}

function reset(){
  data=[];
  $("result").hidden=true;
  $("status").textContent="";
  $("status").className="status";
  $("file").value="";
}

async function readPdf(buf){
  const pdf=await pdfjsLib.getDocument({data:buf}).promise;
  const pages=[];
  for(let n=1;n<=pdf.numPages;n++){
    const c=await (await pdf.getPage(n)).getTextContent();
    pages.push(c.items.map(i=>({str:i.str,x:i.transform[4],y:i.transform[5],w:i.width})));
    $("status").textContent="กำลังอ่านหน้า "+n+"/"+pdf.numPages;
  }
  return pages;
}

async function handle(file){
  if(!file)return;
  reset();
  fileName=file.name.replace(/\.pdf$/i,"");
  try{
    const pages=await readPdf(await file.arrayBuffer());
    const out=PARSERS[current].parse(pages);
    data=out.rows;opening=out.opening;
    if(!data.length){$("status").textContent="ไม่พบรายการในไฟล์นี้ (เลือกเมนูให้ตรงกับธนาคารหรือยัง?)";$("status").className="status err";return;}
    show();
  }catch(e){
    $("status").textContent="อ่านไฟล์ไม่สำเร็จ: "+e.message;
    $("status").className="status err";
  }
}

function cellVal(r,k){
  if(k==="date")return dstr(r.jsDate);
  if(COLS[k].num)return fmt(r[k]);
  return esc(r[k]);
}

function show(){
  const keys=PARSERS[current].keys;
  const wd=data.reduce((s,r)=>s+(r.wd||0),0),dp=data.reduce((s,r)=>s+(r.dp||0),0);
  $("status").textContent="อ่านสำเร็จ";
  $("cards").innerHTML=[["จำนวนรายการ",data.length.toLocaleString()],["ยอดยกมา",fmt(opening)],["ถอนรวม",fmt(wd)],["ฝากรวม",fmt(dp)],["ยอดคงเหลือสุดท้าย",fmt(data[data.length-1].bal)]]
    .map(c=>`<div class="card"><small>${c[0]}</small><b>${c[1]}</b></div>`).join("");
  $("tbl").innerHTML="<tr>"+keys.map(k=>`<th>${COLS[k].h}</th>`).join("")+"</tr>"+data.slice(0,500).map(r=>
    "<tr>"+keys.map(k=>`<td${COLS[k].num?' class="n"':""}>${cellVal(r,k)}</td>`).join("")+"</tr>").join("");
  $("note").textContent=data.length>500?"แสดง 500 รายการแรก ไฟล์ Excel มีครบทุกรายการ":"";
  $("result").hidden=false;
}

function buildWorkbook(rows,open,keys){
  const wb=new ExcelJS.Workbook();
  const sm=wb.addWorksheet("Summary");
  const ws=wb.addWorksheet("Transactions",{views:[{state:"frozen",ySplit:1}]});
  const L=k=>String.fromCharCode(65+keys.indexOf(k));
  const ckCol=String.fromCharCode(65+keys.length);
  ws.columns=keys.map(k=>({header:COLS[k].h,width:COLS[k].w})).concat([{header:"Balance Check",width:14}]);
  ws.getRow(1).eachCell(c=>{c.font={name:"Arial",bold:true,color:{argb:"FFFFFFFF"}};c.fill={type:"pattern",pattern:"solid",fgColor:{argb:"FF1F4E78"}};c.alignment={horizontal:"center",vertical:"middle",wrapText:true};});
  let prevBal=open;
  rows.forEach((r,i)=>{
    const n=i+2;
    const [h,m]=r.time?r.time.split(":").map(Number):[0,0];
    const prev=i===0?"Summary!$B$3":L("bal")+(n-1);
    const ok=Math.abs(prevBal-(r.wd||0)+(r.dp||0)-r.bal)<0.005;
    const vals=keys.map(k=>k==="date"?r.jsDate:k==="time"?(r.time?(h*60+m)/1440:null):r[k]);
    vals.push({formula:`IF(ROUND(${prev}-N(${L("wd")}${n})+N(${L("dp")}${n})-${L("bal")}${n},2)=0,"OK","CHECK")`,result:ok?"OK":"CHECK"});
    ws.addRow(vals);
    prevBal=r.bal;
  });
  const last=rows.length+1;
  ws.eachRow((row,rn)=>{if(rn>1){row.eachCell(c=>c.font={name:"Arial",size:10});
    keys.forEach((k,j)=>{if(COLS[k].fmt)row.getCell(j+1).numFmt=COLS[k].fmt;});}});
  ws.autoFilter={from:"A1",to:ckCol+last};
  const wd=rows.reduce((s,r)=>s+(r.wd||0),0),dp=rows.reduce((s,r)=>s+(r.dp||0),0);
  const cl=rows[rows.length-1].bal;
  [
    ["Statement Summary"],[],
    ["Opening balance (THB)",open],
    ["Total withdrawals (THB)",{formula:`SUM(Transactions!${L("wd")}2:${L("wd")}${last})`,result:wd}],
    ["Total deposits (THB)",{formula:`SUM(Transactions!${L("dp")}2:${L("dp")}${last})`,result:dp}],
    ["Closing balance (calc)",{formula:"B3-B4+B5",result:cl}],
    ["Closing balance (statement)",{formula:`Transactions!${L("bal")}${last}`,result:cl}],
    ["Difference",{formula:"ROUND(B6-B7,2)",result:0}],
    ["Withdrawal count",{formula:`COUNT(Transactions!${L("wd")}2:${L("wd")}${last})`,result:rows.filter(r=>r.wd).length}],
    ["Deposit count",{formula:`COUNT(Transactions!${L("dp")}2:${L("dp")}${last})`,result:rows.filter(r=>r.dp).length}],
    ["Rows failing balance check",{formula:`COUNTIF(Transactions!${ckCol}2:${ckCol}${last},"CHECK")`,result:0}]
  ].forEach(r=>sm.addRow(r));
  sm.columns=[{width:34},{width:20}];
  sm.eachRow((row,rn)=>{row.eachCell(c=>c.font={name:"Arial",size:rn===1?14:10,bold:rn===1});
    if(rn>=3&&rn<=8)row.getCell(2).numFmt="#,##0.00";});
  sm.getCell("B3").font={name:"Arial",size:10,color:{argb:"FF0000FF"}};
  return wb;
}

async function exportXlsx(){
  const wb=buildWorkbook(data,opening,PARSERS[current].keys);
  const buf=await wb.xlsx.writeBuffer();
  const a=document.createElement("a");
  a.href=URL.createObjectURL(new Blob([buf],{type:"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}));
  a.download=fileName+".xlsx";
  a.click();
  URL.revokeObjectURL(a.href);
}

buildMenu();
$("file").onchange=e=>handle(e.target.files[0]);
$("dl").onclick=exportXlsx;
["dragover","dragenter"].forEach(ev=>$("drop").addEventListener(ev,e=>{e.preventDefault();$("drop").classList.add("over");}));
["dragleave","drop"].forEach(ev=>$("drop").addEventListener(ev,e=>{e.preventDefault();$("drop").classList.remove("over");}));
$("drop").addEventListener("drop",e=>handle(e.dataTransfer.files[0]));
