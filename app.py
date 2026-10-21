import streamlit as st
import pandas as pd
import pdfplumber
import re
import io
import xlsxwriter

# ---------------------------------------------------------------------------
# ฟอนต์ในไฟล์ PDF ของ Shopee บางไฟล์เข้ารหัสวรรณยุกต์/การันต์ไทยบางตัวไว้ใน
# Private Use Area (PUA) แทน Unicode ปกติ ทำให้จับคำในหัวตารางไม่เจอ
# ต้องแปลงกลับก่อนเสมอ
# ---------------------------------------------------------------------------
PUA_MAP = {
    "\uf70a": "\u0e48",  # ่ ไม้เอก
    "\uf70b": "\u0e49",  # ้ ไม้โท
    "\uf70e": "\u0e4c",  # ์ การันต์
}

# วรรณยุกต์/สระบน ที่บางครั้งถูกดึงมาผิดลำดับ (เช่น "ซ้ือ" แทน "ซื้อ")
# ตัดออกตอนเทียบคำหัวตาราง เพื่อไม่ให้ลำดับตัวอักษรที่คลาดเคลื่อนทำให้จับคำไม่เจอ
DIACRITICS = re.compile("[\u0e34-\u0e3a\u0e47-\u0e4e]")


def fix_thai(s):
    if not s:
        return s
    for bad, good in PUA_MAP.items():
        s = s.replace(bad, good)
    # บางฟอนต์แยก "ำ" (สระอำ) เป็นนิคหิต (ํ) + สระอา (า) สองตัวอักษร
    # ต้องรวมกลับเป็น "ำ" ตัวเดียว ไม่เช่นนั้นจะจับคำเช่น "ชำระ" ไม่เจอ
    s = s.replace("\u0e4d\u0e32", "\u0e33")
    return s


def skeleton(s):
    """ทำให้ข้อความไทยเทียบกันได้ง่าย: แก้ฟอนต์ + ตัดช่องว่าง + ตัดวรรณยุกต์"""
    s = fix_thai(s) or ""
    s = re.sub(r"\s+", "", s)
    s = DIACRITICS.sub("", s)
    return s


def parse_num(s):
    """แปลงข้อความตัวเลข (รวมเลขติดลบที่ใช้เครื่องหมาย − ของ Shopee) เป็น float"""
    if s is None:
        return None
    s = fix_thai(s).replace("−", "-").replace(",", "").strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def find_column_indices(header_cells):
    """หา index ของคอลัมน์ที่ต้องการ โดยจับคำในหัวตาราง (ไม่ยึดตำแหน่งตายตัว)
    เพราะรายงานแต่ละเดือนอาจมี/ไม่มีบางคอลัมน์ (เช่น "ค่าจัดส่งสินค้าที่ออกโดย Shopee")"""
    idx = {}
    for i, cell in enumerate(header_cells):
        t = skeleton(cell)
        if skeleton("ราคาสินค้า") in t:
            idx["price"] = i
        elif skeleton("คืนให้ผู้ซื้อ") in t:
            idx["refund"] = i
        elif skeleton("ชำระโดยผู้ซื้อ") in t and skeleton("จัดส่ง") in t:
            idx["ship_paid_by_buyer"] = i
    return idx


def parse_summary_totals(page_text):
    """ดึงยอดสรุปจากตาราง 'สรุปจำนวนเงินที่โอนแล้ว' ในหน้าแรก
    ใช้เป็นค่าอ้างอิงเพื่อตรวจสอบว่าดึงข้อมูลรายวันมาครบ/ถูกต้องหรือไม่"""
    text = fix_thai(page_text) or ""
    totals = {}
    patterns = {
        "price": r"ราคาสินค้า\s*([\-\u2212\d,]+)",
        "refund": r"จำนวนเงินที่ทำการคืนให้ผู้ซื้อ\s*([\-\u2212\d,]+)",
        "ship_paid_by_buyer": r"ค่าจัดส่งที่ชำระโดยผู้ซื้อ\s*([\-\u2212\d,]+)",
    }
    for key, pat in patterns.items():
        m = re.search(pat, text)
        if m:
            totals[key] = parse_num(m.group(1))
    return totals


def _assign_column(x0, x1, col_bounds):
    """หา index คอลัมน์จากตำแหน่ง x ของคำ โดยเทียบจุดกึ่งกลางคำกับขอบเขตคอลัมน์"""
    xc = (x0 + x1) / 2
    for i, (cx0, cx1) in enumerate(col_bounds):
        if cx0 <= xc < cx1:
            return i
    return None


def _extract_rows_from_table(page, table):
    """
    สร้างแถวข้อมูลจริงจากตาราง โดยอ่านตำแหน่ง x,y ของคำแต่ละคำบนหน้ากระดาษ
    (ไม่ใช่แค่ข้อความที่ pdfplumber รวมมาให้) เพราะบางค่าตัดขึ้นบรรทัดใหม่กลางคำ
    (เช่น "14,052" กลายเป็น "14," + "052") แต่บางแถวในหน้าเดียวกันไม่ตัด
    (เช่น "1,484" พอดีไม่ต้องตัด) การนับจำนวนชิ้นแล้วหารเฉลี่ยจึงใช้ไม่ได้เสมอไป
    ต้องอิงตำแหน่งจริงว่าแต่ละคำอยู่ "แถวไหน" (โดยดูว่าคอลัมน์วันที่ขึ้นต้นด้วย
    ปี-เดือนหรือไม่ = แถวใหม่) และ "คอลัมน์ไหน" (จากตำแหน่ง x เทียบกับขอบเขตคอลัมน์)

    คืนค่า: (list ของ dict {col_index: ข้อความเต็มของคอลัมน์นั้นในแถวนี้}, คำเตือน)
    """
    warnings = []
    header_row = table.rows[0] if table.rows else None
    # หาแถวที่มีเส้นแบ่งคอลัมน์จริง (แถวหัวตาราง หรือแถวข้อมูล ใช้ขอบเขตเดียวกันทั้งตาราง)
    col_bounds = None
    for row in table.rows:
        if row.cells and all(c is not None for c in row.cells) and len(row.cells) >= 8:
            col_bounds = [(c[0], c[2]) for c in row.cells]
            break
    if not col_bounds:
        return [], warnings

    top = table.bbox[1]
    bottom = table.bbox[3]
    words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    words = [w for w in words if top - 1 <= w["top"] <= bottom + 1]
    words.sort(key=lambda w: (round(w["top"], 1), w["x0"]))

    # จัดกลุ่มคำเป็น "บรรทัดจริง" ตามตำแหน่งแนวตั้ง (top ใกล้กันถือว่าเป็นบรรทัดเดียวกัน)
    lines = []
    current_line = []
    current_top = None
    for w in words:
        if current_top is None or abs(w["top"] - current_top) <= 2.5:
            current_line.append(w)
            current_top = w["top"] if current_top is None else current_top
        else:
            lines.append(current_line)
            current_line = [w]
            current_top = w["top"]
    if current_line:
        lines.append(current_line)

    NUMERIC_OK = re.compile(r"^[0-9,.\-\u2212]+$")

    rows = []
    pending = None  # dict {col_index: text} กำลังสร้างแถวปัจจุบัน

    for line in lines:
        line_cols = {}
        for w in line:
            ci = _assign_column(w["x0"], w["x1"], col_bounds)
            if ci is None:
                continue
            line_cols[ci] = line_cols.get(ci, "") + w["text"]

        date_frag = fix_thai(line_cols.get(0, ""))
        is_new_row = bool(re.match(r"^\d{4}-\d{2}", date_frag))

        if is_new_row:
            if pending is not None:
                rows.append(pending)
            pending = dict(line_cols)
            continue

        # ไม่ใช่จุดเริ่มแถวใหม่ -> เป็นได้แค่ (ก) ส่วนต่อของตัวเลข/วันที่ที่ตัดบรรทัด
        # หรือ (ข) บรรทัดอื่นที่ไม่ใช่ข้อมูล (หัวข้อ/ยอดรวม) ซึ่งมีตัวอักษรปน
        all_numeric = all(NUMERIC_OK.match(fix_thai(v)) for v in line_cols.values() if v)
        if all_numeric and pending is not None:
            for ci, text in line_cols.items():
                pending[ci] = pending.get(ci, "") + text
        else:
            # แถวหัวข้อ/ยอดรวม -> ปิดแถวที่ค้างอยู่ (ถ้ามี) แล้วข้ามบรรทัดนี้ไป
            if pending is not None:
                rows.append(pending)
                pending = None

    if pending is not None:
        rows.append(pending)

    return rows, warnings


def get_shopee_data(file):
    """
    ดึงข้อมูลรายวันจากรายงานการเงิน Shopee (PDF)

    ใช้ pdfplumber อ่านทั้งโครงสร้างตาราง (เส้นตาราง กำหนดขอบเขตคอลัมน์) และตำแหน่ง
    x,y ของคำแต่ละคำบนหน้ากระดาษ (ไม่ใช่แค่นับจำนวนบรรทัดแล้วหารเฉลี่ย) เพราะ:
      1) ตัวเลข/วันที่บางค่าถูกตัดขึ้นบรรทัดใหม่กลางคำเมื่อคอลัมน์แคบ
      2) การตัดบรรทัดไม่ได้เกิดสม่ำเสมอทุกแถวในหน้าเดียวกันเสมอไป (บางแถวตัด บางแถวไม่ตัด)
         จึงต้องอิงตำแหน่งจริงของคำแต่ละคำ ไม่ใช่การเดาสัดส่วน
      3) จำนวนคอลัมน์ในรายงานแต่ละเดือน/ร้านไม่เท่ากันเสมอไป จึงหาคอลัมน์ที่ต้องการ
         จากชื่อหัวตาราง ไม่ใช่ตำแหน่งคงที่

    คืนค่า (DataFrame, list ของข้อความเตือน)
    """
    data = []
    warnings = []
    col_idx = None
    summary_totals = {}

    with pdfplumber.open(file) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            if page_num == 1:
                try:
                    summary_totals = parse_summary_totals(page.extract_text())
                except Exception:
                    pass

            try:
                tables = page.find_tables()
            except Exception as e:
                warnings.append(f"หน้า {page_num}: อ่านตารางไม่ได้ ({e})")
                continue

            for t in tables:
                try:
                    table_data = t.extract()
                except Exception:
                    continue
                if not table_data or len(table_data[0] if table_data else []) < 8:
                    continue

                # หาแถวหัวตาราง (ต้องมีอย่างน้อย "ราคาสินค้า") เพื่อระบุคอลัมน์ที่ต้องการ
                # หมายเหตุ: บางรายงานไม่มีคอลัมน์ "จำนวนเงินที่ทำการคืนให้ผู้ซื้อ" เลย
                # (ร้านไม่มียอดคืนเงินในช่วงนั้น) จึงไม่บังคับว่าต้องเจอครบทุกคอลัมน์
                header_row_i = None
                for ri, row in enumerate(table_data):
                    joined = skeleton("".join(c or "" for c in row))
                    if skeleton("ราคาสินค้า") in joined:
                        header_row_i = ri
                        break
                if header_row_i is not None:
                    new_col_idx = find_column_indices(table_data[header_row_i])
                    if "price" in new_col_idx:
                        col_idx = new_col_idx

                if not col_idx:
                    continue

                row_dicts, w2 = _extract_rows_from_table(page, t)
                warnings.extend(f"หน้า {page_num}: {w}" for w in w2)

                for row_cols in row_dicts:
                    date_text = fix_thai(row_cols.get(0, "")).replace(" ", "")
                    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_text):
                        continue  # ไม่ใช่แถวข้อมูลจริง (เช่นแถวยอดรวม) ข้ามไป
                    entry = {"วันที่โอนเงิน": date_text}
                    for key, out_col in [
                        ("price", "ราคาสินค้า"),
                        ("refund", "ยอดคืนเงิน"),
                        ("ship_paid_by_buyer", "เงินสนับสนุน"),
                    ]:
                        ci = col_idx.get(key)
                        if ci is None:
                            # คอลัมน์นี้ไม่มีในรายงานฉบับนี้เลย (เช่น ไม่มียอดคืนเงินทั้งเดือน) ถือเป็น 0
                            entry[out_col] = 0.0
                            continue
                        val = row_cols.get(ci)
                        if val is None or val == "":
                            warnings.append(
                                f"หน้า {page_num}: แถว {date_text} ไม่พบค่าคอลัมน์ '{key}'"
                            )
                        entry[out_col] = parse_num(val)
                    data.append(entry)

            page.flush_cache()  # ป้องกันหน่วยความจำสะสมเมื่อไฟล์มีหลายหน้า

    df = pd.DataFrame(data)

    # ตรวจสอบผลรวมกับยอดสรุปในตัวรายงานเอง เพื่อความปลอดภัย (ไม่ให้ข้อมูลผิดเงียบๆ)
    if not df.empty and summary_totals:
        check_map = {
            "price": "ราคาสินค้า",
            "refund": "ยอดคืนเงิน",
            "ship_paid_by_buyer": "เงินสนับสนุน",
        }
        for key, col in check_map.items():
            expected = summary_totals.get(key)
            if expected is None or col not in df:
                continue
            actual = df[col].sum(skipna=True)
            if abs(actual - expected) > 1:  # ยอมรับความคลาดเคลื่อนจากการปัดเศษเล็กน้อย
                warnings.append(
                    f"ผลรวมคอลัมน์ '{col}' = {actual:,.0f} แต่ยอดสรุปในรายงานระบุ {expected:,.0f} "
                    f"(ต่างกัน {actual - expected:,.0f}) — กรุณาตรวจสอบข้อมูลก่อนใช้งาน"
                )

    return df, warnings


def get_lazada_data(file):
    """
    ดึงข้อมูลรายวันจากรายงานการเงิน Lazada (PDF)

    ไฟล์ Lazada ไม่มีปัญหาข้อความตัดขึ้นบรรทัดใหม่กลางคำแบบ Shopee — แต่ละแถวข้อมูล
    เป็น 1 บรรทัดสมบูรณ์ในรูปแบบ "วันที่ ยอดรายการขาย ค่าธรรมเนียมฯ ... จำนวนเงิน"
    จึงอ่านด้วย extract_text() ทีละบรรทัดแล้วจับด้วย regex ได้โดยตรง โดยดึงเฉพาะ
    วันที่ และ "ยอดรายการขาย" (ตัวเลขค่าแรกหลังวันที่) ตามที่ต้องการ

    คืนค่า (DataFrame, list ของข้อความเตือน)
    """
    rows = []
    warnings = []
    expected_total = None

    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            text = fix_thai(page.extract_text() or "")

            # ดึงยอดรวม "ยอดรายการขาย" จากแถวท้ายตาราง (รวมจำนวนเงิน ...) ไว้ตรวจสอบ
            m = re.search(r"รวมจำนวนเงิน\s+([\d,]+\.\d{2})", text)
            if m:
                expected_total = parse_num(m.group(1))

            for line in text.split("\n"):
                line = line.strip()
                m = re.match(r"^(\d{2}/\d{2}/\d{4})\s+(.+)$", line)
                if not m:
                    continue
                date_str, rest = m.groups()
                nums = re.findall(r"-?[\d,]+\.\d{2}", rest)
                if not nums:
                    continue
                # แปลงวันที่ dd/mm/yyyy (พ.ศ. ปฏิทินสากลตามที่ระบุในรายงาน) เป็น yyyy-mm-dd
                d, mth, y = date_str.split("/")
                iso_date = f"{y}-{mth}-{d}"
                rows.append({
                    "วันที่ทำรายการ": iso_date,
                    "ยอดรายการขาย": parse_num(nums[0]),
                })

            page.flush_cache()  # ป้องกันหน่วยความจำสะสมเมื่อไฟล์มีหลายหน้า

    df = pd.DataFrame(rows)

    if not df.empty and expected_total is not None:
        actual = df["ยอดรายการขาย"].sum(skipna=True)
        if abs(actual - expected_total) > 1:
            warnings.append(
                f"ผลรวมคอลัมน์ 'ยอดรายการขาย' = {actual:,.2f} แต่ยอดสรุปในรายงานระบุ "
                f"{expected_total:,.2f} (ต่างกัน {actual - expected_total:,.2f}) — กรุณาตรวจสอบข้อมูลก่อนใช้งาน"
            )

    return df, warnings


def _is_line_item_table_header(header_row):
    """เช็คว่าตารางนี้ใช่ตาราง 'รายการค่าใช้จ่าย' หรือไม่ โดยดูจากหัวตาราง
    ต้องมีทั้งคอลัมน์รายการ (รายการ/Description) และคอลัมน์จำนวนเงิน (จำนวนเงิน/Amount)"""
    joined = " ".join((c or "") for c in header_row)
    has_desc = ("รายการ" in joined) or ("Description" in joined)
    has_amount = ("จำนวนเงิน" in joined) or ("Amount" in joined)
    return has_desc and has_amount


def _extract_line_items(data_rows):
    """แยกแถว 'รายการจริง' ออกจากแถวว่าง/แถวสรุปท้ายตาราง (เช่น 'มูลค่าก่อนภาษีมูลค่าเพิ่ม',
    'Total', '7% (VAT)') โดยอาศัยกฎที่ใช้ได้ทั้งใบ Shopee (5 คอลัมน์) และ Lazada (3 คอลัมน์)
    โดยไม่ต้องเขียนแยกกัน: แถวรายการจริงจะขึ้นต้นด้วยเลขลำดับ (ลำดับ/No.) เสมอ ส่วนแถวว่าง
    และแถวสรุปจะไม่ขึ้นต้นด้วยตัวเลข จากนั้นดึง "รายการ" จากเซลล์ข้อความตัวแรกที่ไม่ว่าง
    ถัดจากลำดับ และ "จำนวนเงิน" จากเซลล์ตัวเลขที่อยู่ขวาสุดของแถว (คอลัมน์สุดท้ายเสมอ
    ไม่ว่าตารางจะมีกี่คอลัมน์)"""
    items = []
    for row in data_rows:
        if not row:
            continue
        cells = [c.strip() if isinstance(c, str) else c for c in row]
        first = cells[0]
        if not first or not str(first).strip().isdigit():
            continue  # ไม่ใช่แถวรายการ (แถวว่าง หรือแถวสรุปที่คอลัมน์แรกเป็นข้อความ/None)
        desc = None
        for c in cells[1:-1]:
            if c and str(c).strip():
                desc = str(c).strip()
                break
        if desc is None:
            continue
        amount = None
        for c in reversed(cells[1:]):
            if c and str(c).strip():
                amount = parse_num(str(c).strip())
                break
        if amount is None:
            continue
        items.append({"ลำดับรายการ": str(first).strip(), "รายการ": desc, "จำนวนเงิน": amount})
    return items


def get_expense_line_items(page):
    """หาตาราง 'รายการค่าใช้จ่าย' ในหน้า PDF แล้วดึงรายการย่อยทุกแถวออกมา
    คืนค่า list ว่างถ้าไม่พบตารางแบบนี้ในหน้านั้น (เช่น เอกสารที่ไม่มีตารางรายการ)"""
    try:
        tables = page.find_tables()
    except Exception:
        return []
    for t in tables:
        try:
            rows = t.extract()
        except Exception:
            continue
        if not rows:
            continue
        if _is_line_item_table_header(rows[0]):
            return _extract_line_items(rows[1:])
    return []


def get_lazada_expenses_data(files):
    """
    ดึงข้อมูลจากใบเสร็จ/ใบกำกับภาษี/Credit Note ค่าใช้จ่ายของ Lazada (ไฟล์ PDF หลายหน้า
    แต่ละหน้า = 1 เอกสาร) ดัดแปลงจากสคริปต์ 'Lazada Expenses PDF File read.py' เดิม
    ให้ทำงานกับไฟล์ที่อัปโหลดผ่านเว็บได้ (จากเดิมที่อ่านจากพาธไฟล์ในเครื่อง)

    ดึงรายการย่อยในตาราง 'Code/Descriptions' ของแต่ละใบด้วย (ไม่ใช่แค่ยอดรวม) เพราะแต่ละใบ
    มีรายการไม่เท่ากัน (เช่น Payment Fee, Premium Package, Commission ฯลฯ) จึงคืนค่าเป็น
    ตารางแบบยาว (1 แถว = 1 รายการย่อยของ 1 ใบ) แทนที่จะยัดทุกรายการเป็นคอลัมน์คงที่

    คืนค่า DataFrame คอลัมน์: ไฟล์, Page, Company, Document Type, Document No., Date,
    ลำดับรายการ, รายการ, จำนวนเงิน, ยอดรวมใบ (รวม VAT)
    """
    data_list = []
    for file in files:
        try:
            with pdfplumber.open(file) as pdf:
                for idx, page in enumerate(pdf.pages):
                    text = page.extract_text()
                    if not text:
                        continue
                    lines = [line.strip() for line in text.split("\n") if line.strip()]

                    company_name = "Lazada"
                    doc_type = "Unknown Type"
                    doc_no = "Unknown"
                    doc_date = "Unknown"
                    total_amount = "Unknown"

                    if "Lazada Express" in text or "ลาซาด้า เอ็กซ์เพรส" in text:
                        company_name = "Lazada Express"

                    if "CREDIT NOTE" in text:
                        doc_type = "Credit Note"
                    elif "Shipping Fee Receipt" in text:
                        doc_type = "Shipping Fee"
                    elif "TAX INVOICE" in text:
                        doc_type = "Tax Invoice"

                    for line in lines:
                        if "Credit Note:" in line:
                            m = re.search(r"Credit Note:\s*([A-Za-z0-9\-]+)", line, re.IGNORECASE)
                            if m:
                                doc_no = m.group(1)
                        elif "Invoice No.:" in line:
                            m = re.search(r"Invoice No\.:\s*([A-Za-z0-9\-]+)", line, re.IGNORECASE)
                            if m:
                                doc_no = m.group(1)

                        if "Invoice Date:" in line:
                            m = re.search(r"Invoice Date:\s*([\d\-]+)", line, re.IGNORECASE)
                            if m:
                                doc_date = m.group(1)
                        elif "Date:" in line and "Digitally" not in line:
                            m = re.search(r"Date:\s*([\d\-]+)", line, re.IGNORECASE)
                            if m:
                                doc_date = m.group(1)

                        if "Total (Including Tax)" in line:
                            m = re.search(r"([\d,]+\.\d{2})", line)
                            if m:
                                total_amount = m.group(1)
                        elif "Net Total Shipping Fee" in line:
                            m = re.search(r"([\d,]+\.\d{2})", line)
                            if m:
                                total_amount = m.group(1)

                    if total_amount == "Unknown":
                        all_amounts = []
                        for line in lines:
                            found = re.findall(r"([\d,]+\.\d{2})", line)
                            if found and "7%" not in line and "3%" not in line and "1%" not in line:
                                all_amounts.extend(found)
                        if all_amounts:
                            total_amount = all_amounts[-1]

                    total_amount = parse_num(total_amount) if total_amount != "Unknown" else None

                    items = get_expense_line_items(page)
                    if not items:
                        # ไม่พบตารางรายการ (เช่น รูปแบบเอกสารที่ไม่มีตาราง) -> ใช้ยอดรวมทั้งใบแทน
                        # เพื่อไม่ให้เอกสารนี้หายไปจากรายงานเงียบๆ
                        items = [{
                            "ลำดับรายการ": "",
                            "รายการ": "ไม่สามารถแยกรายการได้ (ใช้ยอดรวมทั้งใบแทน)",
                            "จำนวนเงิน": total_amount,
                        }]

                    for item in items:
                        data_list.append({
                            "ไฟล์": getattr(file, "name", ""),
                            "Page": idx + 1,
                            "Company": company_name,
                            "Document Type": doc_type,
                            "Document No.": doc_no,
                            "Date": doc_date,
                            "ลำดับรายการ": item["ลำดับรายการ"],
                            "รายการ": item["รายการ"],
                            "จำนวนเงิน": item["จำนวนเงิน"],
                            "ยอดรวมใบ (รวม VAT)": total_amount,
                        })

                    page.flush_cache()  # ป้องกันหน่วยความจำสะสมเมื่อไฟล์มีหลายหน้า
        except Exception as e:
            data_list.append({
                "ไฟล์": getattr(file, "name", ""),
                "Page": None,
                "Company": "Lazada",
                "Document Type": f"อ่านไฟล์นี้ไม่สำเร็จ: {e}",
                "Document No.": "Unknown",
                "Date": "Unknown",
                "ลำดับรายการ": "",
                "รายการ": "",
                "จำนวนเงิน": None,
                "ยอดรวมใบ (รวม VAT)": None,
            })

    return pd.DataFrame(data_list)


def get_shopee_expenses_data(files):
    """
    ดึงข้อมูลจากใบเสร็จ/ใบกำกับภาษีค่าใช้จ่ายของ Shopee/SPX Express (ไฟล์ PDF หลายหน้า
    แต่ละหน้า = 1 เอกสาร) ดัดแปลงจากสคริปต์ 'Shoppee Expenses PDF File read.py' เดิม
    ให้ทำงานกับไฟล์ที่อัปโหลดผ่านเว็บได้ (จากเดิมที่อ่านจากพาธไฟล์ในเครื่อง)

    ดึงรายการย่อยในตาราง 'รายการ/Description' ของแต่ละใบด้วย (ไม่ใช่แค่ยอดรวม) เพราะแต่ละใบ
    มีรายการไม่เท่ากัน (เช่น Commission fee, Transaction fee ฯลฯ) จึงคืนค่าเป็นตารางแบบยาว
    (1 แถว = 1 รายการย่อยของ 1 ใบ) แทนที่จะยัดทุกรายการเป็นคอลัมน์คงที่

    คืนค่า DataFrame คอลัมน์: ไฟล์, Page, Company, Document Type, Document No., Date,
    ลำดับรายการ, รายการ, จำนวนเงิน, ยอดรวมใบ (รวม VAT)
    """
    data_list = []
    for file in files:
        try:
            with pdfplumber.open(file) as pdf:
                for idx, page in enumerate(pdf.pages):
                    text = page.extract_text()
                    if not text:
                        continue
                    lines = [line.strip() for line in text.split("\n") if line.strip()]

                    shopee = "Shopee" in text or "Receipt/Tax Invoice" in text
                    spx = "SPX Express" in text or ("Receipt" in text and not shopee)

                    total_amount = "Unknown"
                    doc_no = "Unknown"
                    doc_date = "Unknown"

                    for i, line in enumerate(lines):
                        if ("เลขที่" in line or "No." in line) and re.search(r"[A-Z]{3,}", line):
                            top_match = re.search(r"([A-Z0-9\-]{10,})", line)
                            if top_match:
                                top_no = top_match.group(1)
                                bottom_no = ""
                                if i + 1 < len(lines):
                                    next_line = lines[i + 1]
                                    bottom_match = re.search(r"([0-9]{4,}\-[0-9]{4,})", next_line)
                                    if not bottom_match:
                                        bottom_match = re.search(r"([0-9\-]{6,15})", next_line)
                                    if bottom_match:
                                        bottom_no = bottom_match.group(1)
                                doc_no = f"{top_no} / {bottom_no}" if bottom_no else top_no

                        if "วันที่" in line or "Date" in line:
                            m = re.search(r"(\d{2}/\d{2}/\d{4})", line)
                            if m:
                                doc_date = m.group(1)

                    shopee_match = re.search(r"Included VAT\)?\s*([\d,]+\.\d{2})", text, re.IGNORECASE)
                    if not shopee_match:
                        shopee_match = re.search(
                            r"Total Value of Services \(Included VAT\)\s*([\d,]+\.\d{2})", text, re.IGNORECASE
                        )

                    spx_match = re.search(r"Total amount\s*([\d,]+\.\d{2})", text, re.IGNORECASE)
                    if not spx_match:
                        spx_match = re.search(
                            r"จำนวนเงินรวม/\s*Total\s*amount\s*([\d,]+\.\d{2})", text, re.IGNORECASE
                        )

                    if shopee:
                        company_name = "Shopee"
                        doc_type = "Tax Invoice"
                        if shopee_match:
                            total_amount = shopee_match.group(1)
                    elif spx:
                        company_name = "SPX Express"
                        doc_type = "Shipping Fee"
                        if spx_match:
                            total_amount = spx_match.group(1)
                    else:
                        company_name = "Unknown"
                        doc_type = "Unknown Type"
                        total_match = re.search(r"(?:Total|รวม)\s*([\d,]+\.\d{2})", text, re.IGNORECASE)
                        if total_match:
                            total_amount = total_match.group(1)

                    total_amount = parse_num(total_amount) if total_amount != "Unknown" else None

                    items = get_expense_line_items(page)
                    if not items:
                        # ไม่พบตารางรายการ (เช่น รูปแบบเอกสารที่ไม่มีตาราง) -> ใช้ยอดรวมทั้งใบแทน
                        # เพื่อไม่ให้เอกสารนี้หายไปจากรายงานเงียบๆ
                        items = [{
                            "ลำดับรายการ": "",
                            "รายการ": "ไม่สามารถแยกรายการได้ (ใช้ยอดรวมทั้งใบแทน)",
                            "จำนวนเงิน": total_amount,
                        }]

                    for item in items:
                        data_list.append({
                            "ไฟล์": getattr(file, "name", ""),
                            "Page": idx + 1,
                            "Company": company_name,
                            "Document Type": doc_type,
                            "Document No.": doc_no,
                            "Date": doc_date,
                            "ลำดับรายการ": item["ลำดับรายการ"],
                            "รายการ": item["รายการ"],
                            "จำนวนเงิน": item["จำนวนเงิน"],
                            "ยอดรวมใบ (รวม VAT)": total_amount,
                        })

                    page.flush_cache()  # ป้องกันหน่วยความจำสะสมเมื่อไฟล์มีหลายหน้า
        except Exception as e:
            data_list.append({
                "ไฟล์": getattr(file, "name", ""),
                "Page": None,
                "Company": "Shopee/SPX",
                "Document Type": f"อ่านไฟล์นี้ไม่สำเร็จ: {e}",
                "Document No.": "Unknown",
                "Date": "Unknown",
                "ลำดับรายการ": "",
                "รายการ": "",
                "จำนวนเงิน": None,
                "ยอดรวมใบ (รวม VAT)": None,
            })

    return pd.DataFrame(data_list)


def get_tiktok_expenses_data(files):
    """
    ดึงข้อมูลจากใบเสร็จ/ใบกำกับภาษีค่าใช้จ่ายฝั่ง TikTok Shop (ไฟล์ PDF หลายหน้า
    แต่ละหน้า = 1 เอกสาร) เอกสารมีหลายรูปแบบย่อย เช่น ค่าขนส่ง (Thai Happy Logistics),
    ค่าธรรมเนียม Affiliate (TikTok Pte. Ltd.), ค่าคอมมิชชั่นครีเอเตอร์ (Creator name)
    จึงต้องดึง "เวนเดอร์" (ชื่อที่อยู่มุมซ้ายบนของเอกสาร) แยกออกมาต่างหาก เพราะแต่ละ
    เอกสารเป็นคนละนิติบุคคล/บุคคลกัน

    คืนค่า DataFrame คอลัมน์: ไฟล์, Page, Company, Vendor, Document Type, Document No., Date, Total Amount
    """
    data_list = []
    for file in files:
        try:
            with pdfplumber.open(file) as pdf:
                for idx, page in enumerate(pdf.pages):
                    text = fix_thai(page.extract_text() or "")
                    if not text:
                        continue

                    # --- เวนเดอร์ (ชื่อมุมซ้ายบนของเอกสาร) ---
                    vendor = "Unknown"
                    m = re.search(r"Creator name:\s*(.+)", text)
                    if m:
                        vendor = m.group(1).strip()
                    else:
                        m = re.search(r"^(.*(?:Ltd\.|Co\., Ltd\.|Pte\. Ltd\.).*)$", text, re.MULTILINE)
                        if m:
                            vendor = m.group(1).strip()

                    # --- ประเภทเอกสาร ---
                    if "Creator commission" in text:
                        doc_type = "Creator Commission"
                    elif "Logistics fee" in text or "Logistics" in text:
                        doc_type = "Logistics Fee"
                    elif "Affiliate Service Fee" in text or "Affiliate commission" in text:
                        doc_type = "Affiliate Service Fee"
                    elif "CREDIT NOTE" in text:
                        doc_type = "Credit Note"
                    elif "TAX INVOICE" in text or "Tax Invoice" in text:
                        doc_type = "Tax Invoice"
                    else:
                        doc_type = "Unknown Type"

                    # --- เลขที่เอกสาร (รองรับทั้ง : ปกติ และ ： แบบเต็มความกว้าง, ไม่สนตัวพิมพ์เล็ก-ใหญ่) ---
                    m = re.search(
                        r"(?:Receipt number|Invoice number|Receipt Number|Credit note number)\s*[:：]\s*([A-Za-z0-9]+)",
                        text,
                        re.IGNORECASE,
                    )
                    doc_no = m.group(1) if m else "Unknown"

                    # --- วันที่เอกสาร ---
                    m = re.search(
                        r"(?:Receipt date|Invoice date|Receipt Date|Credit note date)\s*[:：]\s*([A-Za-z]+\s+\d{1,2},\s*\d{4})",
                        text,
                        re.IGNORECASE,
                    )
                    doc_date = m.group(1) if m else "Unknown"

                    # --- ยอดเงินรวม (เอกสารบางแบบเขียน "Total amount" ตัว a เล็ก จึงต้องไม่สนตัวพิมพ์เล็ก-ใหญ่) ---
                    m = re.search(r"Total Amount\D*?([\d,]+\.\d{2})", text, re.IGNORECASE)
                    total_amount = parse_num(m.group(1)) if m else None

                    data_list.append({
                        "ไฟล์": getattr(file, "name", ""),
                        "Page": idx + 1,
                        "Company": "TikTok Shop",
                        "Vendor": vendor,
                        "Document Type": doc_type,
                        "Document No.": doc_no,
                        "Date": doc_date,
                        "Total Amount": total_amount,
                    })

                    page.flush_cache()  # ป้องกันหน่วยความจำสะสมเมื่อไฟล์มีหลายหน้า
        except Exception as e:
            data_list.append({
                "ไฟล์": getattr(file, "name", ""),
                "Page": None,
                "Company": "TikTok Shop",
                "Document Type": f"อ่านไฟล์นี้ไม่สำเร็จ: {e}",
                "Document No.": "Unknown",
                "Date": "Unknown",
                "Total Amount": None,
            })

    return pd.DataFrame(data_list)



# ---------------------------------------------------------------------------
# สเตทเมนต์ธนาคาร (กรุงไทย / กสิกรไทย)
# ---------------------------------------------------------------------------
import datetime
from decimal import Decimal

STM_NUM = r"\d{1,3}(?:,\d{3})*\.\d{2}"
KTB_ROW = re.compile(r"^(\d{2}/\d{2}/\d{2})\s+(.+?)\s+((?:" + STM_NUM + r"\s+)+)(\d{1,4})\s*$")
KTB_TYPE = re.compile(r"^(.*?\([A-Z]+\))\s*(.*)$")
STM_TIME = re.compile(r"^(\d{2}:\d{2})\s*(.*)$")
KBANK_DATE = re.compile(r"^\d{2}-\d{2}-\d{2}$")
KBANK_NUM = re.compile(r"^" + STM_NUM + r"$")

STM_HEADERS = {
    "date": "วันที่", "time": "เวลา", "type": "ประเภทรายการ", "channel": "ช่องทาง",
    "details": "รายละเอียด/อ้างอิง", "wd": "ถอน", "dp": "ฝาก", "bal": "ยอดคงเหลือ", "branch": "สาขา",
}
STM_WIDTHS = {"date": 12, "time": 8, "type": 30, "channel": 22, "details": 46, "wd": 16, "dp": 16, "bal": 18, "branch": 8}
KTB_KEYS = ["date", "time", "type", "details", "wd", "dp", "bal", "branch"]
KBANK_KEYS = ["date", "time", "type", "channel", "details", "wd", "dp", "bal"]


def _stm_to_dec(s):
    return Decimal(s.replace(",", ""))


def _stm_finalize(rows, opening, date_fmt):
    prev = opening
    out = []
    for r in rows:
        diff = r["balance"] - prev
        r["wd"] = float(-diff) if diff < 0 else None
        r["dp"] = float(diff) if diff > 0 else None
        r["bal"] = float(r["balance"])
        d, m, y = (int(x) for x in re.split(r"[/-]", r["date_str"]))
        y = y + 2500 - 543 if date_fmt == "be" else 2000 + y
        r["date"] = datetime.date(y, m, d)
        prev = r["balance"]
        out.append(r)
    return out


def parse_krungthai_statement(file):
    lines = []
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            lines.extend((page.extract_text() or "").split("\n"))
            page.flush_cache()
    rows = []
    i = 0
    while i < len(lines):
        m = KTB_ROW.match(lines[i].strip())
        if not m:
            i += 1
            continue
        d, mid, nums, br = m.groups()
        vals = [_stm_to_dec(x) for x in nums.split()]
        tm = KTB_TYPE.match(mid)
        typ, det = (tm.group(1), tm.group(2)) if tm else (mid, "")
        time_str, extra = "", ""
        if i + 1 < len(lines):
            t = STM_TIME.match(lines[i + 1].strip())
            if t:
                time_str, extra = t.group(1), t.group(2)
                i += 1
        rows.append({
            "date_str": d, "time": time_str, "type": typ.strip(),
            "details": (det + " " + extra).strip(), "amount": vals[-2] if len(vals) >= 2 else Decimal(0),
            "balance": vals[-1], "branch": int(br),
        })
        i += 1
    if not rows:
        return pd.DataFrame(), None
    f = rows[0]
    opening = f["balance"] - f["amount"] if "เข้า" in f["type"] else f["balance"] + f["amount"]
    return pd.DataFrame(_stm_finalize(rows, opening, "be")), float(opening)


def _kbank_fill(row, items):
    for w in items:
        s = w["text"].strip()
        if not s:
            continue
        if re.match(r"^\d{2}:\d{2}$", s) and w["x0"] < 125:
            row["time"] = s
        elif KBANK_NUM.match(s):
            if w["x1"] > 290:
                row["bal"] = _stm_to_dec(s)
            else:
                row["amt"] = _stm_to_dec(s)
        elif w["x0"] < 225:
            row["type"].append(s)
        elif w["x0"] < 402:
            row["channel"].append(s)
        else:
            row["details"].append(s)


def parse_kasikorn_statement(file):
    allrows = []
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            words = [w for w in page.extract_words(keep_blank_chars=False) if w["x0"] >= 60]
            lines = []
            for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
                for ln in lines:
                    if abs(ln["top"] - w["top"]) <= 2.5:
                        ln["items"].append(w)
                        break
                else:
                    lines.append({"top": w["top"], "items": [w]})
            lines.sort(key=lambda ln: ln["top"])
            cur, last = None, 0
            for ln in lines:
                items = sorted(ln["items"], key=lambda w: w["x0"])
                d = next((w for w in items if w["x0"] < 100 and KBANK_DATE.match(w["text"])), None)
                if d is not None:
                    cur = {"date_str": d["text"], "time": "", "type": [], "channel": [], "details": [], "amt": None, "bal": None}
                    allrows.append(cur)
                    _kbank_fill(cur, [w for w in items if w is not d])
                    last = ln["top"]
                elif cur is not None and ln["top"] - last <= 14:
                    _kbank_fill(cur, items)
                    last = ln["top"]
                else:
                    cur = None
            page.flush_cache()
    opening = None
    rows = []
    for r in allrows:
        typ = " ".join(r["type"])
        if "ยอดยกมา" in typ:
            if opening is None:
                opening = r["bal"]
            continue
        if r["bal"] is None:
            continue
        rows.append({
            "date_str": r["date_str"], "time": r["time"], "type": typ, "channel": " ".join(r["channel"]),
            "details": " ".join(r["details"]), "amount": r["amt"] or Decimal(0), "balance": r["bal"],
        })
    if not rows:
        return pd.DataFrame(), None
    if opening is None:
        f = rows[0]
        opening = f["balance"] - f["amount"] if ("รับ" in f["type"] or "ฝาก" in f["type"]) else f["balance"] + f["amount"]
    return pd.DataFrame(_stm_finalize(rows, opening, "ce")), float(opening)


def build_statement_excel(df, opening, keys):
    out = io.BytesIO()
    wb = xlsxwriter.Workbook(out, {"in_memory": True})
    sm = wb.add_worksheet("Summary")
    ws = wb.add_worksheet("Transactions")
    base = {"font_name": "Arial", "font_size": 10}
    f_txt = wb.add_format(base)
    f_head = wb.add_format({**base, "bold": True, "font_color": "#FFFFFF", "bg_color": "#1F4E78", "align": "center", "valign": "vcenter", "text_wrap": True})
    f_date = wb.add_format({**base, "num_format": "dd/mm/yyyy"})
    f_time = wb.add_format({**base, "num_format": "hh:mm"})
    f_num = wb.add_format({**base, "num_format": "#,##0.00"})
    f_ctr = wb.add_format({**base, "align": "center"})
    f_title = wb.add_format({"font_name": "Arial", "font_size": 14, "bold": True})
    f_in = wb.add_format({**base, "num_format": "#,##0.00", "font_color": "#0000FF"})
    L = lambda k: chr(65 + keys.index(k))
    ck = chr(65 + len(keys))
    for j, k in enumerate(keys):
        ws.write(0, j, STM_HEADERS[k], f_head)
        ws.set_column(j, j, STM_WIDTHS[k])
    ws.write(0, len(keys), "ตรวจยอดคงเหลือ", f_head)
    ws.set_column(len(keys), len(keys), 16)
    ws.set_row(0, 30)
    ws.freeze_panes(1, 0)
    prev_bal = opening
    for i, r in enumerate(df.to_dict("records")):
        n = i + 2
        for j, k in enumerate(keys):
            v = r.get(k)
            if k == "date":
                ws.write_datetime(i + 1, j, datetime.datetime.combine(v, datetime.time()), f_date)
            elif k == "time":
                if v:
                    h, mi = (int(x) for x in v.split(":"))
                    ws.write_number(i + 1, j, (h * 60 + mi) / 1440, f_time)
            elif k in ("wd", "dp", "bal"):
                if v is not None and not pd.isna(v):
                    ws.write_number(i + 1, j, float(v), f_num)
            elif k == "branch":
                ws.write_number(i + 1, j, int(v), f_ctr)
            else:
                ws.write(i + 1, j, v or "", f_txt)
        wd = 0 if pd.isna(r["wd"]) else r["wd"]
        dp = 0 if pd.isna(r["dp"]) else r["dp"]
        ok = abs(prev_bal - wd + dp - r["bal"]) < 0.005
        prev = "Summary!$B$3" if i == 0 else f"{L('bal')}{n - 1}"
        ws.write_formula(
            i + 1, len(keys),
            f'=IF(ROUND({prev}-N({L("wd")}{n})+N({L("dp")}{n})-{L("bal")}{n},2)=0,"OK","CHECK")',
            f_ctr, "OK" if ok else "CHECK",
        )
        prev_bal = r["bal"]
    last = len(df) + 1
    ws.autofilter(0, 0, last - 1, len(keys))
    tw = float(df["wd"].sum(skipna=True))
    td = float(df["dp"].sum(skipna=True))
    cl = float(df["bal"].iloc[-1])
    sm.set_column(0, 0, 34)
    sm.set_column(1, 1, 20)
    sm.write(0, 0, "สรุปสเตทเมนต์", f_title)
    items = [
        (2, "ยอดยกมา", opening, None),
        (3, "ถอนรวม", None, (f"=SUM(Transactions!{L('wd')}2:{L('wd')}{last})", tw)),
        (4, "ฝากรวม", None, (f"=SUM(Transactions!{L('dp')}2:{L('dp')}{last})", td)),
        (5, "ยอดคงเหลือ (คำนวณ)", None, ("=B3-B4+B5", opening - tw + td)),
        (6, "ยอดคงเหลือ (ตามสเตทเมนต์)", None, (f"=Transactions!{L('bal')}{last}", cl)),
        (7, "ผลต่าง", None, ("=ROUND(B6-B7,2)", round(opening - tw + td - cl, 2))),
        (8, "จำนวนรายการถอน", None, (f"=COUNT(Transactions!{L('wd')}2:{L('wd')}{last})", int(df["wd"].notna().sum()))),
        (9, "จำนวนรายการฝาก", None, (f"=COUNT(Transactions!{L('dp')}2:{L('dp')}{last})", int(df["dp"].notna().sum()))),
        (10, "แถวที่ตรวจยอดไม่ผ่าน", None, (f'=COUNTIF(Transactions!{ck}2:{ck}{last},"CHECK")', 0)),
    ]
    for row, label, val, fx in items:
        sm.write(row, 0, label, f_txt)
        if fx is None:
            sm.write_number(row, 1, val, f_in)
        else:
            sm.write_formula(row, 1, fx[0], f_num if row <= 7 else wb.add_format({**base, "num_format": "0"}), fx[1])
    wb.close()
    return out.getvalue()


def render_statement(title, parse_fn, keys, key):
    st.write(f"อัปโหลดไฟล์ PDF สเตทเมนต์ {title} (ไฟล์ที่เป็นข้อความ ไม่ใช่ภาพสแกน)")
    up = st.file_uploader(f"เลือกไฟล์ PDF สเตทเมนต์ {title}", type=["pdf"], key=f"{key}_uploader")
    if up is None:
        return
    with st.spinner("กำลังอ่านไฟล์..."):
        try:
            df, opening = parse_fn(up)
        except Exception as e:
            st.error(f"อ่านไฟล์ไม่สำเร็จ: {e}")
            return
    if df.empty:
        st.error(
            "ไม่พบรายการในไฟล์นี้ กรุณาตรวจว่าเลือกธนาคารตรงกับไฟล์ "
            "และไฟล์ไม่ใช่ภาพสแกน (ไฟล์สแกนยังไม่รองรับ)"
        )
        return
    wd = df["wd"].sum(skipna=True)
    dp = df["dp"].sum(skipna=True)
    st.success(f"ดึงข้อมูลสำเร็จ {len(df):,} รายการ")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("ยอดยกมา", f"{opening:,.2f}")
    c2.metric("ถอนรวม", f"{wd:,.2f}")
    c3.metric("ฝากรวม", f"{dp:,.2f}")
    c4.metric("ยอดคงเหลือสุดท้าย", f"{df['bal'].iloc[-1]:,.2f}")
    if abs(opening - wd + dp - df["bal"].iloc[-1]) > 0.005:
        st.warning("ยอดยกมา − ถอน + ฝาก ไม่เท่ากับยอดคงเหลือสุดท้าย กรุณาตรวจสอบข้อมูล")
    show = df[keys].rename(columns=STM_HEADERS)
    st.dataframe(show, use_container_width=True, height=520)
    st.download_button(
        "📥 ดาวน์โหลดไฟล์ Excel",
        data=build_statement_excel(df, opening, keys),
        file_name=f"สเตทเมนต์_{title}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"{key}_download",
    )


def render_statement_ktb():
    render_statement("กรุงไทย", parse_krungthai_statement, KTB_KEYS, "ktb")


def render_statement_kbank():
    render_statement("กสิกรไทย", parse_kasikorn_statement, KBANK_KEYS, "kbank")


st.set_page_config(page_title="สรุปรายได้/ค่าใช้จ่าย", page_icon="📊", layout="wide")


def render_shopee_income():
    st.write("อัปโหลดไฟล์ PDF รายงาน Shopee เพื่อคำนวณยอดสุทธิ")
    uploaded_file = st.file_uploader("เลือกไฟล์ PDF ของ Shopee", type=["pdf"], key="shopee_uploader")
    if uploaded_file is None:
        return
    with st.spinner("กำลังอ่านไฟล์..."):
        df, warnings = get_shopee_data(uploaded_file)
    if df.empty:
        st.error(
            "ไม่สามารถดึงข้อมูลจากไฟล์นี้ได้ กรุณาตรวจสอบว่าเป็นไฟล์รายงานการเงิน Shopee "
            "ที่มีตาราง 'รายละเอียดการโอนเงิน' หรือไม่"
        )
        return
    df["ยอดสุทธิ"] = (df["ราคาสินค้า"] - df["ยอดคืนเงิน"].abs()) + df["เงินสนับสนุน"]
    for w in warnings:
        st.warning(w)
    if not warnings:
        st.success(f"ดึงข้อมูลสำเร็จ {len(df)} แถว และผลรวมตรงกับยอดสรุปในรายงาน ✅")
    st.write("ตัวอย่างข้อมูลที่ดึงได้:")
    st.dataframe(df)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Shopee")
    st.download_button(
        label="📥 ดาวน์โหลดไฟล์ Excel", data=output.getvalue(),
        file_name="สรุปรายได้_Shopee.xlsx", mime="application/vnd.ms-excel", key="shopee_download",
    )


def render_lazada_income():
    st.write("อัปโหลดไฟล์ PDF รายงาน Lazada เพื่อดึงวันที่และยอดรายการขาย")
    uploaded_file_lzd = st.file_uploader("เลือกไฟล์ PDF ของ Lazada", type=["pdf"], key="lazada_uploader")
    if uploaded_file_lzd is None:
        return
    with st.spinner("กำลังอ่านไฟล์..."):
        df_lzd, warnings_lzd = get_lazada_data(uploaded_file_lzd)
    if df_lzd.empty:
        st.error(
            "ไม่สามารถดึงข้อมูลจากไฟล์นี้ได้ กรุณาตรวจสอบว่าเป็นไฟล์รายงานการเงิน Lazada "
            "ที่มีตาราง 'รายละเอียดธุรกรรม' หรือไม่"
        )
        return
    for w in warnings_lzd:
        st.warning(w)
    if not warnings_lzd:
        st.success(f"ดึงข้อมูลสำเร็จ {len(df_lzd)} แถว และผลรวมตรงกับยอดสรุปในรายงาน ✅")
    st.write("ตัวอย่างข้อมูลที่ดึงได้:")
    st.dataframe(df_lzd)
    output_lzd = io.BytesIO()
    with pd.ExcelWriter(output_lzd, engine="xlsxwriter") as writer:
        df_lzd.to_excel(writer, index=False, sheet_name="Lazada")
    st.download_button(
        label="📥 ดาวน์โหลดไฟล์ Excel", data=output_lzd.getvalue(),
        file_name="สรุปรายได้_Lazada.xlsx", mime="application/vnd.ms-excel", key="lazada_download",
    )


def render_lazada_expense():
    st.write("อัปโหลดไฟล์ PDF ใบเสร็จ/ใบกำกับภาษี/Credit Note ค่าใช้จ่ายของ Lazada (อัปโหลดได้หลายไฟล์ แต่ละหน้าถือเป็น 1 เอกสาร)")
    files_lzd_exp = st.file_uploader(
        "เลือกไฟล์ PDF ค่าใช้จ่าย Lazada", type=["pdf"], accept_multiple_files=True, key="lzd_exp_uploader"
    )
    if not files_lzd_exp:
        return
    with st.spinner("กำลังอ่านไฟล์..."):
        df_lzd_exp = get_lazada_expenses_data(files_lzd_exp)
    if df_lzd_exp.empty:
        st.error("ไม่สามารถดึงข้อมูลจากไฟล์ที่อัปโหลดได้")
        return
    st.success(f"ดึงข้อมูลสำเร็จ {len(df_lzd_exp)} รายการ")
    st.write("ตัวอย่างข้อมูลที่ดึงได้:")
    st.dataframe(df_lzd_exp)
    output_lzd_exp = io.BytesIO()
    with pd.ExcelWriter(output_lzd_exp, engine="xlsxwriter") as writer:
        df_lzd_exp.to_excel(writer, index=False, sheet_name="Lazada Expenses")
    st.download_button(
        label="📥 ดาวน์โหลดไฟล์ Excel", data=output_lzd_exp.getvalue(),
        file_name="ค่าใช้จ่าย_Lazada.xlsx", mime="application/vnd.ms-excel", key="lzd_exp_download",
    )


def render_shopee_expense():
    st.write("อัปโหลดไฟล์ PDF ใบเสร็จ/ใบกำกับภาษีค่าใช้จ่ายของ Shopee/SPX Express (อัปโหลดได้หลายไฟล์ แต่ละหน้าถือเป็น 1 เอกสาร)")
    files_shp_exp = st.file_uploader(
        "เลือกไฟล์ PDF ค่าใช้จ่าย Shopee/SPX", type=["pdf"], accept_multiple_files=True, key="shp_exp_uploader"
    )
    if not files_shp_exp:
        return
    with st.spinner("กำลังอ่านไฟล์..."):
        df_shp_exp = get_shopee_expenses_data(files_shp_exp)
    if df_shp_exp.empty:
        st.error("ไม่สามารถดึงข้อมูลจากไฟล์ที่อัปโหลดได้")
        return
    st.success(f"ดึงข้อมูลสำเร็จ {len(df_shp_exp)} รายการ")
    st.write("ตัวอย่างข้อมูลที่ดึงได้:")
    st.dataframe(df_shp_exp)
    output_shp_exp = io.BytesIO()
    with pd.ExcelWriter(output_shp_exp, engine="xlsxwriter") as writer:
        df_shp_exp.to_excel(writer, index=False, sheet_name="Shopee_SPX Expenses")
    st.download_button(
        label="📥 ดาวน์โหลดไฟล์ Excel", data=output_shp_exp.getvalue(),
        file_name="ค่าใช้จ่าย_Shopee_SPX.xlsx", mime="application/vnd.ms-excel", key="shp_exp_download",
    )


def render_tiktok_expense():
    st.write(
        "อัปโหลดไฟล์ PDF ใบเสร็จ/ใบกำกับภาษีค่าใช้จ่ายฝั่ง TikTok Shop "
        "(ค่าขนส่ง / ค่าธรรมเนียม Affiliate / ค่าคอมมิชชั่นครีเอเตอร์ ฯลฯ — อัปโหลดได้หลายไฟล์ แต่ละหน้าถือเป็น 1 เอกสาร)"
    )
    files_ttk_exp = st.file_uploader(
        "เลือกไฟล์ PDF ค่าใช้จ่าย TikTok", type=["pdf"], accept_multiple_files=True, key="ttk_exp_uploader"
    )
    if not files_ttk_exp:
        return
    with st.spinner("กำลังอ่านไฟล์..."):
        df_ttk_exp = get_tiktok_expenses_data(files_ttk_exp)
    if df_ttk_exp.empty:
        st.error("ไม่สามารถดึงข้อมูลจากไฟล์ที่อัปโหลดได้")
        return
    st.success(f"ดึงข้อมูลสำเร็จ {len(df_ttk_exp)} รายการ")
    st.write("ตัวอย่างข้อมูลที่ดึงได้:")
    st.dataframe(df_ttk_exp)
    output_ttk_exp = io.BytesIO()
    with pd.ExcelWriter(output_ttk_exp, engine="xlsxwriter") as writer:
        df_ttk_exp.to_excel(writer, index=False, sheet_name="TikTok Expenses")
    st.download_button(
        label="📥 ดาวน์โหลดไฟล์ Excel", data=output_ttk_exp.getvalue(),
        file_name="ค่าใช้จ่าย_TikTok.xlsx", mime="application/vnd.ms-excel", key="ttk_exp_download",
    )




MENU = {
    "💰 รายได้": [
        ("Shopee", "inc_shopee", render_shopee_income),
        ("Lazada", "inc_lazada", render_lazada_income),
    ],
    "🧾 ค่าใช้จ่าย": [
        ("Shopee / SPX", "exp_shopee", render_shopee_expense),
        ("Lazada", "exp_lazada", render_lazada_expense),
        ("TikTok", "exp_tiktok", render_tiktok_expense),
    ],
    "🏦 สเตทเมนต์": [
        ("กรุงไทย", "stm_ktb", render_statement_ktb),
        ("กสิกรไทย", "stm_kbank", render_statement_kbank),
    ],
}

if "page" not in st.session_state:
    st.session_state.page = "inc_shopee"
current_page = st.session_state.page

st.markdown(
    "<style>section[data-testid='stSidebar'] button{justify-content:flex-start;text-align:left;}"
    "section[data-testid='stSidebar'] div[data-testid='stExpander'] details{border-radius:10px;}</style>",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.title("📊 E-Commerce Summarize")
    for group, items in MENU.items():
        with st.expander(group, expanded=any(k == current_page for _, k, _ in items)):
            for label, key, _ in items:
                active = key == current_page
                if st.button(label, key=f"nav_{key}", use_container_width=True, type="primary" if active else "secondary"):
                    st.session_state.page = key
                    st.rerun()

for group, items in MENU.items():
    for label, key, fn in items:
        if key == current_page:
            st.header(f"{group} › {label}")
            fn()
