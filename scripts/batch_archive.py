import argparse
import csv
import time
from pathlib import Path
from tqdm import tqdm
from src.pipeline import process_file, NoCardError

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", default="data/export")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--delay", type=float, default=12.0)
    args = parser.parse_args()

    photos_dir = Path(args.export) / "photos"
    dateien = sorted([p for p in photos_dir.glob("*.jpg") if "_thumb" not in p.name])[:args.limit]

    out_dir = Path("data/out")
    out_dir.mkdir(parents=True, exist_ok=True)

    archiv_csv = out_dir / "archiv.csv"
    review_csv = out_dir / "review.csv"

    fieldnames = [
        "Expression", "PrimaryMeaning", "Meanings", "ExampleSentence",
        "Grammar", "CEFR", "SynonymsAntonyms", "PersonalNote",
        "Source", "WordType", "Tags", "Confidence", "Filename"
    ]

    erfolg, ausgesondert = 0, 0

    with open(archiv_csv, "w", encoding="utf-8", newline="") as f_out, \
         open(review_csv, "w", encoding="utf-8", newline="") as f_rev:

        w_out = csv.DictWriter(f_out, fieldnames=fieldnames, delimiter="\t")
        w_rev = csv.DictWriter(f_rev, fieldnames=fieldnames, delimiter="\t")

        w_out.writeheader()
        w_rev.writeheader()

        for p in tqdm(dateien, desc="Processing batch"):
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    karte = process_file(str(p))
                    karte["Filename"] = p.name
                    if karte.get("Confidence") == "high":
                        w_out.writerow(karte)
                    else:
                        w_rev.writerow(karte)
                    erfolg += 1
                    break
                except NoCardError:
                    ausgesondert += 1
                    break
                except Exception as e:
                    err_msg = str(e)
                    if ("429" in err_msg or "503" in err_msg) and attempt < max_retries - 1:
                        wait_time = 18 * (attempt + 1)
                        print(f"\n[Limit/Busy] Pause {wait_time}s vor erneutem Versuch fuer {p.name}...")
                        time.sleep(wait_time)
                    else:
                        print(f"\nFehler bei {p.name}: {e}")
                        break

            time.sleep(args.delay)

    print(f"\nFinished! Created {erfolg} cards, discarded {ausgesondert} non-vocabulary items.")
    print(f"Cards: {archiv_csv}")
    print(f"Review: {review_csv}")

if __name__ == "__main__":
    main()
