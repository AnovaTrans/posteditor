"""Render an analysis into downloadable LQA reports (CSV / JSON / Markdown).

Used by the LQA tool; the Post-Editor can reuse it too, but the two apps are
independent by design.
"""
import csv
import io
import json


def findings_csv(findings) -> bytes:
    buf = io.StringIO(newline="")
    w = csv.writer(buf)
    w.writerow(["segment_id", "layer", "category", "severity", "weight", "message",
                "source", "target", "suggestion", "origin"])
    for f in findings:
        w.writerow([f.segment_id, f.layer, f.category, f.severity, f.weight, f.message,
                    f.source, f.target, f.suggestion, f.origin])
    return buf.getvalue().encode("utf-8-sig")


def report_json(stats: dict, score: dict, findings) -> bytes:
    data = {"file": stats, "score": score, "findings": [f.as_dict() for f in findings]}
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


def report_md(stats: dict, score: dict, findings) -> bytes:
    L = [f"# LQA Raporu — {stats.get('file_name', '')}", ""]
    L += [
        "## Özet", "",
        "| Metrik | Değer |", "|---|---|",
        f"| Format | {stats.get('format', '')} |",
        f"| Dil | {stats.get('source_lang', '')} → {stats.get('target_lang', '')} |",
        f"| Toplam segment | {stats.get('total', 0)} |",
        f"| İncelenen segment | {stats.get('reviewable', 0)} |",
        f"| Kelime | {score.get('words', 0)} |",
        f"| LQA skoru (1000 kelime) | **{score.get('lqa_score', 0)}** |",
        f"| Kalite derecesi | **{score.get('grade', '')}** |",
        f"| Kritik / Major / Minor | {score.get('critical',0)} / {score.get('major',0)} / {score.get('minor',0)} |",
        f"| Flaglenen segment | {score.get('flagged_segments', 0)} |",
        "",
    ]
    by_cat = score.get("by_category", {})
    if by_cat:
        L += ["## Kategori dağılımı", "", "| Kategori | Adet |", "|---|---|"]
        L += [f"| {k} | {v} |" for k, v in sorted(by_cat.items(), key=lambda x: -x[1])]
        L.append("")
    L += ["## Bulgular", ""]
    cur = None
    for f in findings:
        if f.segment_id != cur:
            cur = f.segment_id
            L += ["", f"### Segment {f.segment_id}", f"**Kaynak:** {f.source}", f"**Hedef:** {f.target}", ""]
        L.append(f"- **[{f.severity}] {f.layer}/{f.category}** — {f.message}"
                 + (f"  \n  _Öneri:_ {f.suggestion}" if f.suggestion else ""))
    return "\n".join(L).encode("utf-8")
