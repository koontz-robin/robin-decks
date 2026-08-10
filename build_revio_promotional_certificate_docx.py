#!/usr/bin/env python3
"""Build an editable Word version of revio-promotional-certificate.html."""

from __future__ import annotations

import html
import zipfile
from pathlib import Path


OUT = Path("revio-promotional-certificate.docx")
LOGO = Path("revio-logo-white.png")


def esc(text: str) -> str:
    return html.escape(text, quote=False)


def p(
    text: str,
    *,
    size: int = 24,
    color: str = "142033",
    bold: bool = False,
    align: str | None = None,
    before: int = 0,
    after: int = 0,
    line: int | None = None,
    caps: bool = False,
) -> str:
    jc = f"<w:jc w:val=\"{align}\"/>" if align else ""
    spacing = f"<w:spacing w:before=\"{before}\" w:after=\"{after}\"" + (
        f" w:line=\"{line}\" w:lineRule=\"auto\"" if line else ""
    ) + "/>"
    b = "<w:b/>" if bold else ""
    cap = "<w:caps/>" if caps else ""
    return f"""
      <w:p>
        <w:pPr>{jc}{spacing}</w:pPr>
        <w:r>
          <w:rPr><w:rFonts w:ascii=\"Aptos\" w:hAnsi=\"Aptos\"/><w:color w:val=\"{color}\"/><w:sz w:val=\"{size}\"/>{b}{cap}</w:rPr>
          <w:t>{esc(text)}</w:t>
        </w:r>
      </w:p>"""


def empty_p() -> str:
    return "<w:p/>"


def tc(content: str, width: int, *, shade: str | None = None, border_bottom: str | None = None) -> str:
    shd = f"<w:shd w:fill=\"{shade}\"/>" if shade else ""
    bottom = (
        f"<w:tcBorders><w:bottom w:val=\"single\" w:sz=\"{border_bottom}\" w:space=\"0\" w:color=\"071426\"/></w:tcBorders>"
        if border_bottom
        else ""
    )
    return f"""
      <w:tc>
        <w:tcPr><w:tcW w:w=\"{width}\" w:type=\"dxa\"/>{shd}{bottom}</w:tcPr>
        {content}
      </w:tc>"""


def tr(cells: str, height: int | None = None) -> str:
    h = f"<w:trPr><w:trHeight w:val=\"{height}\" w:hRule=\"atLeast\"/></w:trPr>" if height else ""
    return f"<w:tr>{h}{cells}</w:tr>"


def image_run() -> str:
    return """
      <w:p>
        <w:pPr><w:spacing w:before="0" w:after="0"/></w:pPr>
        <w:r>
          <w:drawing>
            <wp:inline distT="0" distB="0" distL="0" distR="0">
              <wp:extent cx="1905000" cy="494500"/>
              <wp:effectExtent l="0" t="0" r="0" b="0"/>
              <wp:docPr id="1" name="Rev.io logo"/>
              <wp:cNvGraphicFramePr/>
              <a:graphic>
                <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
                  <pic:pic>
                    <pic:nvPicPr>
                      <pic:cNvPr id="2" name="revio-logo-white.png"/>
                      <pic:cNvPicPr/>
                    </pic:nvPicPr>
                    <pic:blipFill>
                      <a:blip r:embed="rIdLogo"/>
                      <a:stretch><a:fillRect/></a:stretch>
                    </pic:blipFill>
                    <pic:spPr>
                      <a:xfrm><a:off x="0" y="0"/><a:ext cx="1905000" cy="494500"/></a:xfrm>
                      <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
                    </pic:spPr>
                  </pic:pic>
                </a:graphicData>
              </a:graphic>
            </wp:inline>
          </w:drawing>
        </w:r>
      </w:p>"""


def field(label: str, width: int) -> str:
    return tc(
        empty_p()
        + p(label, size=18, color="5F6D80", bold=True, caps=True, before=80, after=0),
        width,
        border_bottom="18",
    )


def document_xml() -> str:
    offer_text = [
        "$250 credit off of monthly fees for 12 months following onboarding graduation",
        "15,000 Revii credits included ($150 value)",
        "2 Summit tickets ($1,300 value)",
    ]
    offers = "".join(
        tr(
            tc(p("\u2713", size=22, color="FFFFFF", bold=True, align="center"), 420, shade="1FB36F")
            + tc(p(item, size=26, bold=True, after=60), 4700, shade="F4F8FC"),
            height=760,
        )
        for item in offer_text
    )

    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas"
  xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
  xmlns:o="urn:schemas-microsoft-com:office:office"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
  xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"
  xmlns:v="urn:schemas-microsoft-com:vml"
  xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing"
  xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
  xmlns:w10="urn:schemas-microsoft-com:office:word"
  xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
  xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"
  xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup"
  xmlns:wpi="http://schemas.microsoft.com/office/word/2010/wordprocessingInk"
  xmlns:wne="http://schemas.microsoft.com/office/word/2006/wordml"
  xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
  xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
  xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"
  mc:Ignorable="w14 wp14">
  <w:body>
    <w:tbl>
      <w:tblPr>
        <w:tblW w:w="14400" w:type="dxa"/>
        <w:tblBorders>
          <w:top w:val="single" w:sz="18" w:space="0" w:color="0057FF"/>
          <w:left w:val="single" w:sz="18" w:space="0" w:color="0057FF"/>
          <w:bottom w:val="single" w:sz="18" w:space="0" w:color="0057FF"/>
          <w:right w:val="single" w:sz="18" w:space="0" w:color="0057FF"/>
          <w:insideH w:val="nil"/>
          <w:insideV w:val="nil"/>
        </w:tblBorders>
        <w:tblCellMar>
          <w:top w:w="160" w:type="dxa"/>
          <w:left w:w="220" w:type="dxa"/>
          <w:bottom w:w="160" w:type="dxa"/>
          <w:right w:w="220" w:type="dxa"/>
        </w:tblCellMar>
      </w:tblPr>
      {tr(tc(image_run(), 7200, shade="071426") + tc(p("Promotional Certificate", size=20, color="E8F3FF", bold=True, align="right", caps=True), 7200, shade="0057FF"), height=1160)}
      {tr(tc(p("Limited-Time Partner Offer", size=20, color="0057FF", bold=True, caps=True, after=160) + p("Up to 7 seats for the price of 5!", size=58, color="071426", bold=True, line=720, after=160) + p("A Rev.io growth package built for teams ready to move faster with Revii and field execution.", size=25, color="5F6D80", bold=True, line=330), 6900) + tc(f"<w:tbl><w:tblPr><w:tblW w:w=\"5120\" w:type=\"dxa\"/><w:tblBorders><w:top w:val=\"single\" w:sz=\"8\" w:color=\"DBE5F2\"/><w:left w:val=\"single\" w:sz=\"8\" w:color=\"DBE5F2\"/><w:bottom w:val=\"single\" w:sz=\"8\" w:color=\"DBE5F2\"/><w:right w:val=\"single\" w:sz=\"8\" w:color=\"DBE5F2\"/><w:insideH w:val=\"single\" w:sz=\"6\" w:color=\"D9E3EF\"/><w:insideV w:val=\"nil\"/></w:tblBorders></w:tblPr>{offers}</w:tbl>", 7500, shade="F4F8FC"), height=5200)}
      {tr(field("Company Name", 4100) + field("Contact", 3500) + field("Date", 2600) + field("Sales Represenative", 4200), height=1160)}
      {tr(tc(p("Rev.io promotional certificate", size=17, color="78869A", bold=True, caps=True), 11000) + tc(p("SUMMIT\\nPASS\\nINCLUDED", size=15, color="0057FF", bold=True, align="center"), 3400), height=760)}
    </w:tbl>
    <w:sectPr>
      <w:pgSz w:w="15840" w:h="12240" w:orient="landscape"/>
      <w:pgMar w:top="360" w:right="360" w:bottom="360" w:left="360" w:header="0" w:footer="0" w:gutter="0"/>
    </w:sectPr>
  </w:body>
</w:document>"""


def write_docx() -> None:
    if not LOGO.exists():
        raise FileNotFoundError(LOGO)

    parts = {
        "[Content_Types].xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>""",
        "_rels/.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>""",
        "word/_rels/document.xml.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rIdLogo" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/revio-logo-white.png"/>
</Relationships>""",
        "word/document.xml": document_xml(),
        "docProps/core.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>Rev.io Promotional Certificate</dc:title>
  <dc:creator>Robin</dc:creator>
  <cp:lastModifiedBy>Robin</cp:lastModifiedBy>
</cp:coreProperties>""",
        "docProps/app.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Robin</Application>
</Properties>""",
    }

    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED) as docx:
        for name, content in parts.items():
            docx.writestr(name, content.encode("utf-8"))
        docx.write(LOGO, "word/media/revio-logo-white.png")


if __name__ == "__main__":
    write_docx()
    print(f"Wrote {OUT}")
