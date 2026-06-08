#!/usr/bin/env python3
"""Build the weekly Tigerpaw Web migration forecast Excel template."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


OUT = Path("tigerpaw-web-migration-weekly-template.xlsx")


def xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def inline(value: str) -> str:
    return f'<is><t xml:space="preserve">{xml_escape(value)}</t></is>'


def cell(ref: str, value: str | int | float = "", style: int | None = None, formula: str | None = None) -> str:
    attrs = [f'r="{ref}"']
    if style is not None:
        attrs.append(f's="{style}"')
    if formula is not None:
        return f'<c {" ".join(attrs)}><f>{xml_escape(formula)}</f></c>'
    if isinstance(value, (int, float)):
        return f'<c {" ".join(attrs)}><v>{value}</v></c>'
    return f'<c {" ".join(attrs)} t="inlineStr">{inline(value)}</c>'


def row(num: int, cells: list[str], height: int | None = None) -> str:
    ht = f' ht="{height}" customHeight="1"' if height else ""
    return f'<row r="{num}"{ht}>{"".join(cells)}</row>'


sheet_rows = [
    row(1, [cell("A1", "Tigerpaw Web Migration Weekly Forecast", 1)], 28),
    row(2, [cell("A2", "Fill in the blue cells each week. The completed script updates automatically.", 2)]),
    row(4, [cell("A4", "Rep Name", 3), cell("B4", "", 4), cell("D4", "Week Of", 3), cell("E4", "", 4)]),
    row(5, [cell("A5", "Last Updated", 3), cell("B5", "", 4), cell("D5", "Manager", 3), cell("E5", "", 4)]),
    row(7, [cell("A7", "Weekly Inputs", 5)]),
    row(8, [cell("A8", "Metric", 6), cell("B8", "Input", 6), cell("C8", "Notes", 6)]),
    row(9, [cell("A9", "Open Tigerpaw Web migration opportunities", 7), cell("B9", "", 4), cell("C9", "Count of currently open migration opps.", 8)]),
    row(10, [cell("A10", "Total renewal amount", 7), cell("B10", "", 9), cell("C10", "Total renewal value for open migration opps.", 8)]),
    row(11, [cell("A11", "Potential increase", 7), cell("B11", "", 9), cell("C11", "Expected MRR or renewal lift.", 8)]),
    row(12, [cell("A12", "Forecasted migration opportunities this month", 7), cell("B12", "", 4), cell("C12", "Count expected to migrate this month.", 8)]),
    row(13, [cell("A13", "Forecasted monthly renewal amount", 7), cell("B13", "", 9), cell("C13", "Total renewal amount tied to monthly forecast.", 8)]),
    row(14, [cell("A14", "Client meetings remaining this week", 7), cell("B14", "", 4), cell("C14", "Remaining Tigerpaw Web migration client meetings this week.", 8)]),
    row(15, [cell("A15", "Client meetings scheduled next week", 7), cell("B15", "", 4), cell("C15", "Already scheduled for next week.", 8)]),
    row(17, [cell("A17", "Completed Script", 5)]),
    row(18, [cell("A18", "", 10, 'CONCATENATE("I currently have ",B9," open Tigerpaw web migration opportunities worth a total renewal amount of ",TEXT(B10,"$#,##0")," with a potential increase of ",TEXT(B11,"$#,##0"),".")')], 45),
    row(19, [cell("A19", "", 10, 'CONCATENATE("I am forecasting ",B12," migration opportunities for this month worth a total renewal amount of ",TEXT(B13,"$#,##0"),".")')], 45),
    row(20, [cell("A20", "", 10, 'CONCATENATE("I have ",B14," Tigerpaw web migration client meetings remaining this week and ",B15," scheduled for next week.")')], 45),
    row(22, [cell("A22", "Optional Deal Detail", 5)]),
    row(23, [
        cell("A23", "Account", 6),
        cell("B23", "Opp Owner", 6),
        cell("C23", "Stage", 6),
        cell("D23", "Renewal Amount", 6),
        cell("E23", "Potential Increase", 6),
        cell("F23", "Forecast Month", 6),
        cell("G23", "Next Meeting", 6),
        cell("H23", "Notes", 6),
    ]),
]

for row_num in range(24, 44):
    sheet_rows.append(
        row(
            row_num,
            [
                cell(f"A{row_num}", "", 11),
                cell(f"B{row_num}", "", 11),
                cell(f"C{row_num}", "", 11),
                cell(f"D{row_num}", "", 12),
                cell(f"E{row_num}", "", 12),
                cell(f"F{row_num}", "", 11),
                cell(f"G{row_num}", "", 11),
                cell(f"H{row_num}", "", 11),
            ],
        )
    )

sheet_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheetViews><sheetView workbookViewId="0" showGridLines="0"><pane ySplit="8" topLeftCell="A9" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>
  <sheetFormatPr defaultRowHeight="18"/>
  <cols>
    <col min="1" max="1" width="42" customWidth="1"/>
    <col min="2" max="2" width="18" customWidth="1"/>
    <col min="3" max="3" width="48" customWidth="1"/>
    <col min="4" max="8" width="20" customWidth="1"/>
  </cols>
  <sheetData>{"".join(sheet_rows)}</sheetData>
  <mergeCells count="5">
    <mergeCell ref="A1:H1"/>
    <mergeCell ref="A2:H2"/>
    <mergeCell ref="A7:H7"/>
    <mergeCell ref="A17:H17"/>
    <mergeCell ref="A22:H22"/>
  </mergeCells>
  <dataValidations count="2">
    <dataValidation type="whole" allowBlank="1" sqref="B9 B12 B14 B15"><formula1>0</formula1><formula2>999</formula2></dataValidation>
    <dataValidation type="decimal" allowBlank="1" sqref="B10:B11 B13 D24:E43"><formula1>0</formula1><formula2>999999999</formula2></dataValidation>
  </dataValidations>
  <pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>
</worksheet>'''

styles_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="4">
    <font><sz val="11"/><color rgb="FF1F2937"/><name val="Aptos"/></font>
    <font><b/><sz val="18"/><color rgb="FFFFFFFF"/><name val="Aptos Display"/></font>
    <font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Aptos"/></font>
    <font><i/><sz val="10"/><color rgb="FF64748B"/><name val="Aptos"/></font>
  </fonts>
  <fills count="7">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF0F172A"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF1E293B"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFE0F2FE"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFDBEAFE"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFF8FAFC"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="3">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border><left style="thin"><color rgb="FFCBD5E1"/></left><right style="thin"><color rgb="FFCBD5E1"/></right><top style="thin"><color rgb="FFCBD5E1"/></top><bottom style="thin"><color rgb="FFCBD5E1"/></bottom><diagonal/></border>
    <border><bottom style="thin"><color rgb="FF94A3B8"/></bottom></border>
  </borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="13">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1"><alignment horizontal="center"/></xf>
    <xf numFmtId="0" fontId="2" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"/>
    <xf numFmtId="0" fontId="0" fillId="4" borderId="1" xfId="0" applyFill="1" applyBorder="1"/>
    <xf numFmtId="0" fontId="2" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>
    <xf numFmtId="0" fontId="2" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"/>
    <xf numFmtId="0" fontId="0" fillId="6" borderId="1" xfId="0" applyFill="1" applyBorder="1"/>
    <xf numFmtId="0" fontId="3" fillId="6" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment wrapText="1"/></xf>
    <xf numFmtId="164" fontId="0" fillId="4" borderId="1" xfId="0" applyNumberFormat="1" applyFill="1" applyBorder="1"/>
    <xf numFmtId="0" fontId="0" fillId="5" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1"><alignment wrapText="1" vertical="center"/></xf>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1"/>
    <xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1"/>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
  <numFmts count="1"><numFmt numFmtId="164" formatCode="$#,##0"/></numFmts>
</styleSheet>'''

workbook_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Weekly Forecast" sheetId="1" r:id="rId1"/></sheets>
</workbook>'''

rels_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>'''

workbook_rels_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>'''

content_types_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>'''


with ZipFile(OUT, "w", ZIP_DEFLATED) as archive:
    archive.writestr("[Content_Types].xml", content_types_xml)
    archive.writestr("_rels/.rels", rels_xml)
    archive.writestr("xl/workbook.xml", workbook_xml)
    archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
    archive.writestr("xl/styles.xml", styles_xml)
    archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)

print(f"Wrote {OUT} ({OUT.stat().st_size:,} bytes)")
