import csv
import sys
from collections import Counter

def load_csv(path):
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        rows = list(reader)
    return rows

def detect_format(header):
    # Box form has "Pack 1 Foil Slot" style headers; pack form has just "Foil Slot"
    return "box" if any("Pack 1" in col for col in header) else "pack"

def parse_responses(rows):
    header = rows[0]
    data = rows[1:]
    fmt = detect_format(header)

    foil_values = []
    last_values = []
    rune_token_values = []
    foil_last_pairs = []  # (foil, last) for conditional analysis

    for row in data:
        pack_count = 24 if fmt == "box" else 1

        for pack_idx in range(pack_count):
            base = 2 + pack_idx * 4
            if base + 3 >= len(row):
                continue

            foil = row[base].strip()
            last = row[base + 1].strip()
            rune = row[base + 2].strip()
            token = row[base + 3].strip()

            if foil:
                foil_values.append(foil)
            if last:
                last_values.append(last)
            if foil and last:
                foil_last_pairs.append((foil, last))

            if rune:
                rune_token_values.append(rune)
            elif token:
                rune_token_values.append(token)

    return foil_values, last_values, rune_token_values, foil_last_pairs

def print_breakdown(label, values):
    total = len(values)
    if total == 0:
        print(f"\n{label}: no data\n")
        return

    counts = Counter(values)
    print(f"\n{label} (n={total})")
    print("-" * 40)
    for value, count in sorted(counts.items(), key=lambda x: -x[1]):
        pct = count / total * 100
        print(f"  {value:<30} {count:>4}  ({pct:.1f}%)")

ABOVE_RARE = {"Epic", "Alt-Art", "Overnumber", "Overnumber Signature", "Ultimate"}

def print_above_rare_when_foil_low(foil_last_pairs):
    low_foil = [(f, l) for f, l in foil_last_pairs if f in ("Common", "Uncommon")]
    total = len(low_foil)
    above = sum(1 for _, l in low_foil if l in ABOVE_RARE)

    print(f"\nLast Slot above Rare when Foil Slot was Common or Uncommon")
    print("-" * 40)
    if total == 0:
        print("  No data.")
        return
    print(f"  Above Rare:  {above:>4}  ({above/total*100:.1f}%)")
    print(f"  Rare:        {total-above:>4}  ({(total-above)/total*100:.1f}%)")
    print(f"  Total packs: {total}")

    breakdown = Counter(l for _, l in low_foil if l in ABOVE_RARE)
    if breakdown:
        print(f"\n  Breakdown of above-Rare results:")
        for val, count in sorted(breakdown.items(), key=lambda x: -x[1]):
            print(f"    {val:<28} {count:>4}  ({count/total*100:.1f}%)")

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "Unleashed Box Form (Responses) - Form responses 1.csv"
    rows = load_csv(path)
    foil, last, rune_token, pairs = parse_responses(rows)

    print_breakdown("Foil Slot (11th card)", foil)
    print_breakdown("Last Slot (13th card)", last)
    print_breakdown("Rune / Token Slot (14th card)", rune_token)
    print_above_rare_when_foil_low(pairs)

if __name__ == "__main__":
    main()
