from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

STYLE = """
* { box-sizing: border-box; }
body { margin:0; padding:22px; background:#fff;
       font-family:"Apple SD Gothic Neo","Helvetica Neue",Arial,sans-serif; color:#111; }
h2 { font-size:15pt; margin:0 0 14px; }
.flow { display:flex; flex-direction:column; gap:7px; width:560px; }
.row { display:flex; align-items:center; gap:9px; }
.box { border:1.4px solid #333; border-radius:6px; padding:8px 12px; font-size:10.5pt;
       background:#fff; flex:1; }
.box .k { font-weight:700; }
.box .s { color:#666; font-size:9pt; }
.engine { background:#eef3f8; border-color:#2c5d8f; }
.slm { background:#fdf4ec; border-color:#b5722c; }
.policy { background:#eef7ee; border-color:#2f7a37; }
.arrow { text-align:center; color:#888; font-size:12pt; line-height:1; }
.ledger { display:grid; grid-template-columns:repeat(5,1fr); gap:7px; width:620px; }
.led { border:1.3px solid #444; border-radius:6px; padding:7px; font-size:8.6pt; text-align:center; }
.led b { display:block; font-size:9.4pt; margin-bottom:3px; }
.led .w { display:block; margin-top:4px; color:#b03030; font-size:7.8pt; line-height:1.3; }
.bars { width:640px; }
.bargroup { margin-bottom:17px; }
.bartitle { font-size:10.5pt; font-weight:700; margin-bottom:6px; }
.bar { display:flex; align-items:center; gap:9px; margin-bottom:5px; font-size:9.5pt; }
.barlabel { width:170px; text-align:right; color:#333; }
.bartrack { flex:1; background:#f0f0f0; border-radius:3px; height:19px; position:relative; }
.barfill { height:100%; border-radius:3px; }
.barval { width:104px; font-size:8.8pt; color:#444; }
.ci { position:absolute; top:4px; height:11px; border-left:1.6px solid #333;
      border-right:1.6px solid #333; }
.ci::after { content:""; position:absolute; top:5px; left:0; right:0; border-top:1.4px solid #333; }
.note { font-size:8.6pt; color:#666; margin-top:9px; }
"""

COLORS = {"M0P0": "#c0504d", "M1P0": "#e8a33d", "M1P1": "#3a7d44"}
FIGURE_CONDITIONS = ("M0P0", "M1P0", "M1P1")


def architecture_html() -> str:
    def box(cls: str, key: str, sub: str) -> str:
        return f'<div class="box {cls}"><span class="k">{key}</span><br><span class="s">{sub}</span></div>'

    flow = "".join(
        f'<div class="row">{b}</div><div class="arrow">&#9660;</div>'
        for b in [
            box("slm", "[1] SLM 입력 이해", "JSON Schema 강제 · claim_predicate enum 8종"),
            box("", "[2] Player Claim 원장", "save_claim — 주장으로만 저장, 사실 확정 없음"),
            box("policy", "[3] 결정", "M0P0·M1P0: SLM 자유 선택 / M1P1: 승격 결정표"),
            box("", "[4] 승격", "accept_as_belief 일 때만 NPC Belief 생성"),
            box("slm", "[5] SLM 대사 표현", "승인된 결정을 한국어로"),
        ]
    )
    flow += f'<div class="row">{box("engine", "[6] 게임 엔진", "World Truth 쓰기 독점 · 원자적 거래 · Committed Event")}</div>'

    ledgers = "".join(
        f'<div class="led"><b>{name}</b>{desc}<span class="w">{guard}</span></div>'
        for name, desc, guard in [
            ("World Truth", "골드·재고·예약", "CHECK source=game_engine"),
            ("Committed Event", "실제 일어난 사건", "append-only"),
            ("Player Claim", "주장 (미검증)", "risk·evidence enum"),
            ("NPC Belief", "NPC 가 믿는 것", "claim_id 로 출처 추적"),
            ("Generated Text", "모델 생성 문장", "CHECK memory_eligible=0"),
        ]
    )
    return (f'<h2>그림 1. 권한 분리형 NPC 대화 파이프라인</h2><div class="flow">{flow}</div>'
            f'<h2 style="margin-top:22px">그림 2. 5종 기억 원장과 구조적 제약</h2>'
            f'<div class="ledger">{ledgers}</div>'
            f'<div class="note">붉은 글씨는 SQLite CHECK 제약으로 DB 레벨에서 강제되는 불변조건이다.</div>')


def results_html(rows: list[dict]) -> str:
    groups = [
        ("CCR — 플레이어 주장 오염률 (낮을수록 좋음)", "CCR", True),
        ("TCAR — 참 주장 수용률 (높을수록 좋음)", "TCAR", True),
        ("Claim Decision Macro-F1 (높을수록 좋음)", "MacroF1", False),
        ("PCFBR — 거짓 믿음 봉쇄율 (높을수록 좋음)", "PCFBR", True),
    ]
    blocks = []
    for title, key, has_ci in groups:
        bars = []
        for row in rows:
            try:
                value = float(row[key])
            except (TypeError, ValueError):
                continue
            if value != value:
                continue
            width = max(1.0, value * 100)
            ci = ""
            if has_ci and row.get(f"{key}_lo") not in (None, ""):
                lo, hi = float(row[f"{key}_lo"]) * 100, float(row[f"{key}_hi"]) * 100
                ci = f'<div class="ci" style="left:{lo}%;width:{max(hi - lo, 0.6)}%"></div>'
            n = row.get(f"{key}_n", "")
            bars.append(
                f'<div class="bar"><div class="barlabel">{row["condition"]} {row["label"]}</div>'
                f'<div class="bartrack"><div class="barfill" style="width:{width}%;'
                f'background:{COLORS.get(row["condition"], "#888")}"></div>{ci}</div>'
                f'<div class="barval">{value:.3f}{f" (n={n})" if n else ""}</div></div>'
            )
        if bars:
            blocks.append(f'<div class="bargroup"><div class="bartitle">{title}</div>{"".join(bars)}</div>')
    return (f'<h2>그림 3. 조건별 지표 (95% Wilson 신뢰구간)</h2>'
            f'<div class="bars">{"".join(blocks)}</div>'
            f'<div class="note">세 조건은 동일 모델·seed·시나리오·평가 코드를 쓰며 '
            f'기억 입력과 결정 주체만 다르다.</div>')


def render(html: str, out_png: Path, width: int, height: int) -> None:
    page = (f'<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">'
            f"<style>{STYLE}</style></head><body>{html}</body></html>")
    tmp = out_png.with_suffix(".html")
    tmp.write_text(page, encoding="utf-8")
    out_png.unlink(missing_ok=True)
    proc = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         f"--window-size={width},{height}", f"--screenshot={out_png}",
         f"--user-data-dir=/tmp/fig-chrome-{out_png.stem}", f"file://{tmp}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if out_png.exists() and out_png.stat().st_size > 0:
            break
        time.sleep(0.4)
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    if not (out_png.exists() and out_png.stat().st_size > 0):
        raise RuntimeError(f"렌더 실패: {out_png}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make_figures")
    parser.add_argument("--metrics", default=str(ROOT / "results" / "metrics.csv"))
    args = parser.parse_args(argv)

    out = ROOT / "figures"
    render(architecture_html(), out / "fig1_architecture.png", 660, 710)
    print(f"생성: {out / 'fig1_architecture.png'}")

    metrics = Path(args.metrics)
    if metrics.exists():
        with metrics.open(encoding="utf-8") as handle:
            rows = [r for r in csv.DictReader(handle)
                    if r["condition"] in FIGURE_CONDITIONS]
        render(results_html(rows), out / "fig3_results.png", 700, 620)
        print(f"생성: {out / 'fig3_results.png'} (조건 {len(rows)}개)")
    else:
        print(f"결과표 없음, 그림 3 생략: {metrics}")
    print("FIGURES_DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
