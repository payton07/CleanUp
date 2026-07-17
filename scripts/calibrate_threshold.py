#!/usr/bin/env python3
"""Calibrate the EmbeddingClassifier cosine threshold on a labeled corpus.

Builds (or reuses) a directory whose subfolders are ground-truth category names,
scores every file with the *real* EmbeddingClassifier against a running Ollama
embedding model, then sweeps thresholds to find the one that best separates
correct matches from wrong/none matches.

Usage:
    python scripts/calibrate_threshold.py [--corpus DIR] [--model NAME]

A folder named "_NONE_" holds negatives that should stay in TEXTS (expected: no
category above threshold).
"""

from __future__ import annotations

import argparse
import statistics
from pathlib import Path

from cleanup.ai.backends import resolve_embedder
from cleanup.ai.classify import DEFAULT_AI_CATEGORIES, EmbeddingClassifier

NONE_LABEL = "_NONE_"

# label -> list of (filename, content). Realistic, varied, a few per category.
SAMPLES: dict[str, list[tuple[str, str]]] = {
    "INVOICES": [
        ("acme_invoice.txt", "INVOICE #4471\nBill to: Acme Corp\nItem: Consulting 20h\nAmount due: $2,300\nDue date: 2026-08-01\nPayment terms: net 30"),
        ("receipt_march.txt", "Receipt\nStore: Bright Foods\nTotal paid: 47.90 EUR\nVAT included\nThank you for your payment"),
    ],
    "REPORTS": [
        ("q2_report.txt", "Quarterly Business Report — Q2 2026\nExecutive summary: revenue grew 12%.\nKey findings and analysis of market trends follow.\nConclusion: outlook positive."),
        ("study_results.txt", "Research Report: Effects of X on Y\nMethodology, results, and statistical analysis.\nFindings indicate a significant correlation."),
    ],
    "CONTRACTS": [
        ("service_agreement.txt", "SERVICE AGREEMENT\nThis contract is entered into by the parties.\nTerms and conditions. The Client agrees to the following clauses.\nSignature: ____________"),
        ("nda.txt", "NON-DISCLOSURE AGREEMENT\nThe undersigned agree to keep confidential information secret.\nLegal terms apply. Governing law clause included."),
    ],
    "LETTERS": [
        ("thank_you.txt", "Dear Mrs. Johnson,\nThank you so much for your hospitality during my visit.\nIt was a pleasure. I look forward to seeing you again.\nWarm regards,\nMarie"),
        ("complaint.txt", "Dear Sir or Madam,\nI am writing to express my dissatisfaction with the service received.\nI would appreciate a prompt response.\nSincerely,\nJohn Davis"),
    ],
    "RESUMES": [
        ("cv_dupont.txt", "Curriculum Vitae — Jean Dupont\nWork experience: Software Engineer at TechCo (2020-2026).\nSkills: Python, Docker, Kubernetes.\nEducation: MSc Computer Science."),
        ("resume_data.txt", "RESUME\nProfessional experience in data engineering.\nSkills: SQL, Spark, ETL pipelines.\nCertifications and references available on request."),
    ],
    "NOTES": [
        ("meeting_notes.txt", "Meeting notes 2026-07-10\n- Discuss roadmap\n- TODO: follow up with design\n- Reminder: send recap\nIdeas for next sprint."),
        ("todo.txt", "TODO\n- buy groceries\n- call the plumber\n- reminder: dentist appointment friday\nrandom ideas jotted down"),
    ],
    "LOGS": [
        ("app.log", "2026-07-16 08:12:01 ERROR database connection timeout\n2026-07-16 08:12:05 WARN retrying\n2026-07-16 08:12:09 DEBUG stack trace follows"),
        ("access.log", "2026-07-16 10:00:01 INFO GET /api/users 200\n2026-07-16 10:00:02 ERROR 500 internal server error\nstack trace: NullPointer"),
    ],
    "CONFIG": [
        ("settings.txt", "# configuration file\nhost: localhost\nport: 8080\ndebug: true\nenv: production\ndatabase_url: postgres://..."),
        ("app_ini.txt", "[server]\nhost = 0.0.0.0\nport = 9000\n[env]\nLOG_LEVEL = info\nsettings and environment variables"),
    ],
    "DATA": [
        ("sales.txt", "date,product,units,revenue\n2026-01-01,widget,120,2400\n2026-01-02,gadget,80,1600\nrows and columns of records"),
        ("measurements.txt", "id;temperature;humidity\n1;21.4;55\n2;22.1;53\n3;20.9;60\ntabular dataset of sensor records"),
    ],
    "RECIPES": [
        ("cake.txt", "Chocolate Cake Recipe\nIngredients: 2 eggs, flour, sugar, cocoa.\nSteps: mix, pour, bake at 180C for 25 min in the oven."),
        ("soup.txt", "Vegetable Soup\nIngredients: carrots, onions, celery, stock.\nCooking steps: chop, simmer for 30 minutes, season to taste."),
    ],
    "EBOOKS": [
        ("chapter1.txt", "Chapter One\nThe rain fell softly on the old town as Elena walked the cobbled streets.\nIt was the beginning of a long story, a novel of love and loss."),
        ("excerpt.txt", "Chapter Twelve\nThe hero faced his greatest challenge yet. The narrative unfolded across many pages of this book."),
    ],
    NONE_LABEL: [
        ("random.txt", "asdf qwer zxcv random tokens 8842 blorp fnord widget-less nonsense text here"),
        ("mixed.txt", "the quick brown fox jumps over the lazy dog several times in a row for testing"),
    ],
}


def build_corpus(root: Path) -> None:
    for label, files in SAMPLES.items():
        d = root / label
        d.mkdir(parents=True, exist_ok=True)
        for name, content in files:
            (d / name).write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=None)
    parser.add_argument("--backend", choices=["auto", "local", "ollama"], default="auto")
    parser.add_argument("--model", default=None, help="Ollama embedding model (ollama backend)")
    args = parser.parse_args()

    root = args.corpus
    generated = root is None
    if generated:
        import tempfile
        root = Path(tempfile.mkdtemp(prefix="cleanup_calib_"))
        build_corpus(root)

    embedder, threshold, label = resolve_embedder(args.backend, ollama_model=args.model)
    if embedder is None:
        raise SystemExit(label)
    print(f"backend: {label}  (current threshold: {threshold})")

    clf = EmbeddingClassifier(embedder, DEFAULT_AI_CATEGORIES)

    # Score every file: (true_label, predicted_label, score)
    rows: list[tuple[str, str | None, float]] = []
    for label_dir in sorted(root.iterdir()):
        if not label_dir.is_dir():
            continue
        true = label_dir.name
        for f in sorted(label_dir.iterdir()):
            if f.is_file():
                pred, score = clf.best_match(f)
                rows.append((true, pred, score))

    print(f"\nCorpus: {root}  ({len(rows)} files, model: {embedder.embed_model})\n")

    # Per-file detail
    print(f"{'true':<10} {'predicted':<12} {'score':>6}  ok")
    print("-" * 40)
    correct_scores, wrong_scores = [], []
    for true, pred, score in rows:
        top1_ok = (pred == true) if true != NONE_LABEL else True  # NONE: top-1 label doesn't matter
        (correct_scores if (pred == true) else wrong_scores).append(score)
        flag = "✓" if (true != NONE_LABEL and pred == true) else ("·" if true == NONE_LABEL else "✗")
        print(f"{true:<10} {str(pred):<12} {score:>6.3f}  {flag}")

    if correct_scores:
        print(f"\ncorrect top-1 scores : min={min(correct_scores):.3f} "
              f"mean={statistics.mean(correct_scores):.3f} max={max(correct_scores):.3f}")
    if wrong_scores:
        print(f"wrong   top-1 scores : min={min(wrong_scores):.3f} "
              f"mean={statistics.mean(wrong_scores):.3f} max={max(wrong_scores):.3f}")

    # Threshold sweep
    positives = [(t, p, s) for (t, p, s) in rows if t != NONE_LABEL]
    negatives = [(t, p, s) for (t, p, s) in rows if t == NONE_LABEL]
    total = len(rows)

    print(f"\n{'thresh':>6} {'accuracy':>9} {'pos_cov':>8} {'pos_prec':>9} {'neg_rej':>8}")
    print("-" * 44)
    best = None
    t = 0.30
    while t <= 0.70001:
        accepted_pos = [(tr, p, s) for (tr, p, s) in positives if s >= t]
        correct_pos = sum(1 for (tr, p, s) in accepted_pos if p == tr)
        rejected_neg = sum(1 for (tr, p, s) in negatives if s < t)
        # overall accuracy: positives correct-accepted + negatives correctly-rejected
        n_correct = correct_pos + rejected_neg
        accuracy = n_correct / total
        pos_cov = len(accepted_pos) / len(positives) if positives else 0
        pos_prec = correct_pos / len(accepted_pos) if accepted_pos else 0
        neg_rej = rejected_neg / len(negatives) if negatives else 0
        marker = ""
        if best is None or accuracy > best[1] or (accuracy == best[1] and pos_cov > best[2]):
            best = (round(t, 2), accuracy, pos_cov, pos_prec, neg_rej)
        print(f"{t:>6.2f} {accuracy:>9.2f} {pos_cov:>8.2f} {pos_prec:>9.2f} {neg_rej:>8.2f}{marker}")
        t += 0.02

    print("\n" + "=" * 44)
    print(f"RECOMMENDED threshold = {best[0]}  "
          f"(accuracy={best[1]:.2f}, coverage={best[2]:.2f}, precision={best[3]:.2f}, neg_reject={best[4]:.2f})")

    # Confusion for wrong top-1 predictions
    confusions = [(t, p, s) for (t, p, s) in positives if p != t]
    if confusions:
        print("\nMisclassified (top-1 wrong):")
        for tr, p, s in sorted(confusions, key=lambda r: -r[2]):
            print(f"  {tr:<10} → {str(p):<12} score={s:.3f}")

    if generated:
        print(f"\n(temporary corpus at {root})")


if __name__ == "__main__":
    main()
