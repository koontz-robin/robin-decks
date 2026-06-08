#!/usr/bin/env python3
"""Build a Rev.io-branded weekly Tigerpaw Web migration forecast workbook."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


OUT = Path("tigerpaw-web-migration-weekly-template.xlsx")


def esc(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def inline(value: str) -> str:
    return f'<is><t xml:space="preserve">{esc(value)}</t></is>'


def cell(ref: str, value: str | int | float = "", style: int = 0, formula: str | None = None) -> str:
    attrs = f'r="{ref}" s="{style}"'
    if formula:
        return f"<c {attrs}><f>{esc(formula)}</f></c>"
    if isinstance(value, (int, float)):
        return f"<c {attrs}><v>{value}</v></c>"
    if value == "":
        return f"<c {attrs}/>"
    return f'<c {attrs} t="inlineStr">{inline(value)}</c>'


def row(num: int, cells: list[str], height: int | None = None, style: int | None = None) -> str:
    attrs = [f'r="{num}"']
    if height:
        attrs.append(f'ht="{height}" customHeight="1"')
    if style is not None:
        attrs.append(f's="{style}" customFormat="1"')
    return f"<row {' '.join(attrs)}>{''.join(cells)}</row>"


def blank_row(num: int, cols: range, style: int) -> str:
    cells = [cell(f"{chr(64 + col)}{num}", "", style) for col in cols]
    return row(num, cells, style=style)


rows: list[str] = []

rows.extend(
    [
        row(2, [cell("F2", "FORECAST SCRIPT", 2), cell("O2", "rev.io", 3)], 28),
        row(3, [cell("F3", "Tigerpaw Web Migration Weekly Update", 4), cell("O3", "Sales Team Repo", 5)], 24),
        row(6, [cell("B6", "Rep Name", 6), cell("E6", "", 7), cell("J6", "Week Of", 6), cell("M6", "", 7)], 22),
        row(7, [cell("B7", "Manager", 6), cell("E7", "", 7), cell("J7", "Last Updated", 6), cell("M7", "", 7)], 22),
        row(9, [cell("B9", "Weekly fill-in script", 8)], 24),
        row(
            11,
            [
                cell("B11", "I currently have", 9),
                cell("E11", "", 10),
                cell("G11", "open Tigerpaw web migration opportunities worth a total renewal amount of", 9),
                cell("O11", "", 11),
                cell("Q11", "with a potential increase of", 9),
                cell("V11", "", 11),
            ],
            28,
        ),
        row(
            13,
            [
                cell("B13", "I am forecasting", 12),
                cell("E13", "", 10),
                cell("G13", "migration opportunities for this month worth a total renewal amount of", 12),
                cell("O13", "", 11),
            ],
            28,
        ),
        row(
            15,
            [
                cell("B15", "I have", 9),
                cell("E15", "", 10),
                cell("G15", "Tigerpaw web migration client meetings remaining this week and", 9),
                cell("O15", "", 10),
                cell("Q15", "scheduled for next week.", 9),
            ],
            28,
        ),
        row(18, [cell("B18", "Completed script", 8)], 24),
        row(
            20,
            [
                cell(
                    "B20",
                    "",
                    13,
                    'CONCATENATE("I currently have ",E11," open Tigerpaw web migration opportunities worth a total renewal amount of ",TEXT(O11,"$#,##0")," with a potential increase of ",TEXT(V11,"$#,##0"),".")',
                )
            ],
            42,
        ),
        row(
            21,
            [
                cell(
                    "B21",
                    "",
                    13,
                    'CONCATENATE("I am forecasting ",E13," migration opportunities for this month worth a total renewal amount of ",TEXT(O13,"$#,##0"),".")',
                )
            ],
            42,
        ),
        row(
            22,
            [
                cell(
                    "B22",
                    "",
                    13,
                    'CONCATENATE("I have ",E15," Tigerpaw web migration client meetings remaining this week and ",O15," scheduled for next week.")',
                )
            ],
            42,
        ),
        row(25, [cell("B25", "Optional deal detail", 8)], 24),
        row(
            27,
            [
                cell("B27", "Account", 14),
                cell("E27", "Opp Owner", 14),
                cell("G27", "Stage", 14),
                cell("I27", "Renewal Amount", 14),
                cell("K27", "Potential Increase", 14),
                cell("M27", "Forecast Month", 14),
                cell("O27", "Next Meeting", 14),
                cell("Q27", "Notes", 14),
            ],
            24,
        ),
    ]
)

for r in range(28, 43):
    rows.append(
        row(
            r,
            [
                cell(f"B{r}", "", 15),
                cell(f"E{r}", "", 15),
                cell(f"G{r}", "", 15),
                cell(f"I{r}", "", 16),
                cell(f"K{r}", "", 16),
                cell(f"M{r}", "", 15),
                cell(f"O{r}", "", 15),
                cell(f"Q{r}", "", 15),
            ],
            22,
        )
    )

merge_refs = [
    "F2:N2",
    "O2:V2",
    "F3:N3",
    "O3:V3",
    "B9:V9",
    "B11:D11",
    "G11:N11",
    "Q11:U11",
    "B13:D13",
    "G13:N13",
    "B15:D15",
    "G15:N15",
    "Q15:V15",
    "B18:V18",
    "B20:V20",
    "B21:V21",
    "B22:V22",
    "B25:V25",
    "B27:D27",
    "E27:F27",
    "G27:H27",
    "I27:J27",
    "K27:L27",
    "M27:N27",
    "O27:P27",
    "Q27:V27",
]
for r in range(28, 43):
    merge_refs.extend([f"B{r}:D{r}", f"E{r}:F{r}", f"G{r}:H{r}", f"I{r}:J{r}", f"K{r}:L{r}", f"M{r}:N{r}", f"O{r}:P{r}", f"Q{r}:V{r}"])

merge_xml = "".join(f'<mergeCell ref="{ref}"/>' for ref in merge_refs)

sheet_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheetViews><sheetView workbookViewId="0" showGridLines="0"><pane ySplit="9" topLeftCell="A10" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>
  <sheetFormatPr defaultRowHeight="18"/>
  <cols>
    <col min="1" max="1" width="3" customWidth="1"/>
    <col min="2" max="4" width="11" customWidth="1"/>
    <col min="5" max="5" width="11" customWidth="1"/>
    <col min="6" max="6" width="3" customWidth="1"/>
    <col min="7" max="14" width="11" customWidth="1"/>
    <col min="15" max="15" width="13" customWidth="1"/>
    <col min="16" max="16" width="3" customWidth="1"/>
    <col min="17" max="22" width="11" customWidth="1"/>
    <col min="23" max="23" width="3" customWidth="1"/>
  </cols>
  <sheetData>{''.join(rows)}</sheetData>
  <mergeCells count="{len(merge_refs)}">{merge_xml}</mergeCells>
  <dataValidations count="2">
    <dataValidation type="whole" operator="between" allowBlank="1" sqref="E11 E13 E15 O15"><formula1>0</formula1><formula2>999</formula2></dataValidation>
    <dataValidation type="decimal" operator="between" allowBlank="1" sqref="O11 V11 O13 I28:K42"><formula1>0</formula1><formula2>999999999</formula2></dataValidation>
  </dataValidations>
  <pageMargins left="0.4" right="0.4" top="0.5" bottom="0.5" header="0.3" footer="0.3"/>
</worksheet>'''

styles_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <numFmts count="1"><numFmt numFmtId="164" formatCode="$#,##0"/></numFmts>
  <fonts count="7">
    <font><sz val="11"/><color rgb="FF0F172A"/><name val="Aptos"/></font>
    <font><b/><sz val="20"/><color rgb="FFFFFFFF"/><name val="Aptos Display"/></font>
    <font><b/><sz val="24"/><color rgb="FFFFFFFF"/><name val="Aptos Display"/></font>
    <font><sz val="11"/><color rgb="FFE0F2FE"/><name val="Aptos"/></font>
    <font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Aptos"/></font>
    <font><b/><sz val="11"/><color rgb="FF0F172A"/><name val="Aptos"/></font>
    <font><sz val="12"/><color rgb="FF0F172A"/><name val="Aptos"/></font>
  </fonts>
  <fills count="9">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF0B1220"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF111827"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFE0F2FE"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFDCFCE7"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF38BDF8"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFF8FAFC"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFECFEFF"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="4">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border><left style="thin"><color rgb="FFCBD5E1"/></left><right style="thin"><color rgb="FFCBD5E1"/></right><top style="thin"><color rgb="FFCBD5E1"/></top><bottom style="thin"><color rgb="FFCBD5E1"/></bottom><diagonal/></border>
    <border><left style="medium"><color rgb="FF0F172A"/></left><right style="medium"><color rgb="FF0F172A"/></right><top style="medium"><color rgb="FF0F172A"/></top><bottom style="medium"><color rgb="FF0F172A"/></bottom><diagonal/></border>
    <border><bottom style="thin"><color rgb="FF38BDF8"/></bottom></border>
  </borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="17">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="0" fillId="2" borderId="0" xfId="0" applyFill="1"/>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="2" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment horizontal="right" vertical="center"/></xf>
    <xf numFmtId="0" fontId="3" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment horizontal="center"/></xf>
    <xf numFmtId="0" fontId="3" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment horizontal="right"/></xf>
    <xf numFmtId="0" fontId="4" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="right"/></xf>
    <xf numFmtId="0" fontId="0" fillId="7" borderId="2" xfId="0" applyFill="1" applyBorder="1"/>
    <xf numFmtId="0" fontId="4" fillId="3" borderId="0" xfId="0" applyFont="1" applyFill="1"/>
    <xf numFmtId="0" fontId="5" fillId="4" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="6" fillId="8" borderId="2" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="164" fontId="6" fillId="8" borderId="2" xfId="0" applyNumberFormat="1" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="5" fillId="5" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="6" fillId="5" borderId="2" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment wrapText="1" vertical="center"/></xf>
    <xf numFmtId="0" fontId="4" fillId="6" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center"/></xf>
    <xf numFmtId="0" fontId="0" fillId="7" borderId="1" xfId="0" applyFill="1" applyBorder="1"/>
    <xf numFmtId="164" fontId="0" fillId="7" borderId="1" xfId="0" applyNumberFormat="1" applyFill="1" applyBorder="1"/>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>'''

workbook_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Forecast Script" sheetId="1" r:id="rId1"/></sheets>
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
