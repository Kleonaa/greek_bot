import argparse
import csv
import io
import subprocess
import unicodedata
from pathlib import Path


ARTICLES = {
    "ο",
    "η",
    "το",
    "οι",
    "τα",
    "τον",
    "την",
    "τους",
    "τις",
    "του",
    "της",
    "ένα",
    "μια",
    "μία",
}

ALIASES = {
    "λέω": ["λέγω"],
    "πώ": ["λέγω"],
    "τρώω": ["τρώγω"],
    "φέρνω": ["φέρω"],
    "φοβάμαι": ["φοβούμαι"],
    "παραγγέλνω": ["παραγγέλλω"],
    "ενδιαφέρομαι": ["ενδιαφέρω"],
    "κουράζομαι": ["κουράζω"],
}

CURATED_FIRST = [
    "έχω",
    "είμαι",
    "κάνω",
    "λέω",
    "θέλω",
    "μπορώ",
    "ξέρω",
    "βλέπω",
    "ακούω",
    "πηγαίνω",
    "έρχομαι",
    "παίρνω",
    "δίνω",
    "τρώω",
    "πίνω",
    "φέρνω",
    "ρωτάω",
    "απαντώ",
    "περνώ",
    "αρχίζω",
    "τελειώνω",
    "ξεκινώ",
    "σταματάω",
    "μένω",
    "φεύγω",
    "γυρίζω",
    "μπαίνω",
    "βγαίνω",
    "αγοράζω",
    "πουλάω",
    "πληρώνω",
    "δουλεύω",
    "διαβάζω",
    "γράφω",
    "μιλάω",
    "μαθαίνω",
    "καταλαβαίνω",
    "θυμάμαι",
    "ξεχνώ",
    "χρειάζομαι",
    "χρησιμοποιώ",
    "περιμένω",
    "ψάχνω",
    "βρίσκω",
    "αγαπάω",
    "φοβάμαι",
    "νιώθω",
    "σκέφτομαι",
    "κοιμάμαι",
    "ξυπνώ",
    "κολυμπώ",
    "περπατώ",
    "ταξιδεύω",
    "οδηγώ",
    "παραγγέλνω",
    "μαγειρεύω",
    "τώρα",
    "σήμερα",
    "χθες",
    "αύριο",
    "εδώ",
    "εκεί",
    "πού",
    "πώς",
    "πότε",
    "γιατί",
    "πολύ",
    "λίγο",
    "καλά",
    "μαζί",
    "μόνο",
    "πάντα",
    "ποτέ",
    "συχνά",
    "συνήθως",
    "μερικές φορές",
    "καμιά φορά",
    "μέσα",
    "έξω",
    "πάνω",
    "κάτω",
    "πίσω",
    "μπροστά",
    "κοντά",
    "μακριά",
    "το σπίτι",
    "η μέρα",
    "η ημέρα",
    "η ώρα",
    "ο χρόνος",
    "ο μήνας",
    "το πρωί",
    "το μεσημέρι",
    "η νύχτα",
    "το παιδί",
    "η μητέρα",
    "ο πατέρας",
    "η μαμά",
    "ο μπαμπάς",
    "η οικογένεια",
    "ο φίλος",
    "η φίλη",
    "το νερό",
    "το φαγητό",
    "ο καφές",
    "το ψωμί",
    "το γάλα",
    "το κρέας",
    "το ψάρι",
    "το φρούτο",
    "το λαχανικό",
    "το μαγαζί",
    "το σούπερμάρκετ",
    "η ταβέρνα",
    "η δουλειά",
    "το σχολείο",
    "το μάθημα",
    "η πόλη",
    "ο δρόμος",
    "η στάση",
    "το λεωφορείο",
    "το μετρό",
    "το αυτοκίνητο",
    "το τηλέφωνο",
    "το κινητό",
    "ο υπολογιστής",
    "τα χρήματα",
    "η τράπεζα",
    "η κάρτα",
    "η τιμή",
    "ο λογαριασμός",
    "το πρόβλημα",
    "η ερώτηση",
    "η απάντηση",
    "η λέξη",
    "καλός",
    "κακός",
    "μεγάλος",
    "μικρός",
    "νέος",
    "παλιός",
    "ωραίος",
    "εύκολος",
    "δύσκολος",
    "σωστός",
    "λάθος",
    "ζεστός",
    "κρύος",
    "ακριβός",
    "φθηνός",
    "πεινασμένος",
    "κουρασμένος",
    "άρρωστος",
    "χαρούμενος",
    "λυπημένος",
]


def normalize_final_sigma(text: str) -> str:
    return text.strip().lower().replace("ς", "σ")


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", normalize_final_sigma(text))
    stripped = "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )
    return unicodedata.normalize("NFC", stripped)


def parse_word_line(line: str) -> tuple[str, str, str]:
    greek, _, translation = line.partition("–")
    greek = greek.strip()
    translation = translation.strip()
    parts = greek.split()
    if len(parts) > 1 and parts[0].lower() in ARTICLES:
        headword = " ".join(parts[1:])
    else:
        headword = greek
    return greek, headword, translation


def matching_candidates(headword: str) -> list[tuple[str, str]]:
    candidates = [(headword, "exact")]
    normalized = normalize_final_sigma(headword)

    for alias in ALIASES.get(normalized, []):
        candidates.append((alias, "alias"))

    if headword.endswith("ώ"):
        candidates.append((headword[:-1] + "άω", "verb_alt"))
    if headword.endswith("άω"):
        candidates.append((headword[:-2] + "ώ", "verb_alt"))

    return candidates


def load_greeklex(zip_path: Path) -> tuple[dict, dict]:
    raw = subprocess.check_output(
        [
            "unzip",
            "-p",
            str(zip_path),
            "GreekLex2.1/encodings/UTF-8/GreekLex2.txt",
        ]
    )
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    exact = {}
    accentless = {}

    for row in reader:
        word = row["Word"].strip()
        if not word:
            continue
        lemma_freq = float(row["LemmaFreq"] or 0)
        word_freq = float(row["WordFreq"] or 0)
        zipf_freq = float(row["zipfFreq"] or 0)
        item = {
            "word": word,
            "lemma_freq": lemma_freq,
            "word_freq": word_freq,
            "zipf_freq": zipf_freq,
            "pos": row.get("Pos", "").strip(),
        }

        exact_key = normalize_final_sigma(word)
        if exact_key not in exact or lemma_freq > exact[exact_key]["lemma_freq"]:
            exact[exact_key] = item

        accentless_key = strip_accents(word)
        if (
            accentless_key not in accentless
            or lemma_freq > accentless[accentless_key]["lemma_freq"]
        ):
            accentless[accentless_key] = item

    ranked = sorted(exact.values(), key=lambda item: item["lemma_freq"], reverse=True)
    for rank, item in enumerate(ranked, start=1):
        exact[normalize_final_sigma(item["word"])]["greeklex_rank"] = rank

    return exact, accentless


def rank_words(words_path: Path, greeklex_zip: Path) -> list[dict]:
    exact, accentless = load_greeklex(greeklex_zip)
    rows = []
    seen = {}

    for original_order, line in enumerate(
        words_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue

        greek, headword, translation = parse_word_line(line)
        exact_key = normalize_final_sigma(headword)
        match = None
        match_type = ""
        for candidate, candidate_type in matching_candidates(headword):
            match = exact.get(normalize_final_sigma(candidate))
            if match:
                match_type = candidate_type
                break
        if not match:
            for candidate, candidate_type in matching_candidates(headword):
                match = accentless.get(strip_accents(candidate))
                if match:
                    match_type = f"{candidate_type}_accentless"
                    break

        duplicate_of = seen.get(exact_key, "")
        seen.setdefault(exact_key, original_order)

        greeklex_rank = match.get("greeklex_rank") if match else ""
        lemma_freq = match.get("lemma_freq") if match else ""
        word_freq = match.get("word_freq") if match else ""
        zipf_freq = match.get("zipf_freq") if match else ""
        pos = match.get("pos") if match else ""
        matched_word = match.get("word") if match else ""

        rows.append(
            {
                "original_order": original_order,
                "learning_order": "",
                "greek": greek,
                "headword": headword,
                "translation": translation,
                "greeklex_rank": greeklex_rank,
                "lemma_freq": lemma_freq,
                "word_freq": word_freq,
                "zipf_freq": zipf_freq,
                "pos": pos,
                "matched_word": matched_word,
                "match_type": match_type,
                "duplicate_of": duplicate_of,
            }
        )

    rows.sort(
        key=lambda row: (
            row["greeklex_rank"] == "",
            row["greeklex_rank"] if row["greeklex_rank"] != "" else 999999,
            row["original_order"],
        )
    )
    for learning_order, row in enumerate(rows, start=1):
        row["learning_order"] = learning_order
    return rows


def curated_rows(ranked_rows: list[dict]) -> list[dict]:
    priority = {}
    for index, word in enumerate(CURATED_FIRST, start=1):
        priority[normalize_final_sigma(word)] = index

    rows = [dict(row) for row in ranked_rows]
    rows.sort(
        key=lambda row: (
            priority.get(normalize_final_sigma(row["greek"]), 999999),
            priority.get(normalize_final_sigma(row["headword"]), 999999),
            row["greeklex_rank"] == "",
            row["greeklex_rank"] if row["greeklex_rank"] != "" else 999999,
            row["original_order"],
        )
    )
    for learning_order, row in enumerate(rows, start=1):
        row["learning_order"] = learning_order
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--words", type=Path, default=Path("words.txt"))
    parser.add_argument(
        "--greeklex-zip", type=Path, default=Path("/tmp/GreekLex2.1.zip")
    )
    parser.add_argument("--output", type=Path, default=Path("data/words_ranked.csv"))
    parser.add_argument(
        "--learning-output", type=Path, default=Path("data/learning_order.csv")
    )
    args = parser.parse_args()

    rows = rank_words(args.words, args.greeklex_zip)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    learning_rows = curated_rows(rows)
    args.learning_output.parent.mkdir(parents=True, exist_ok=True)
    with args.learning_output.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(learning_rows[0]))
        writer.writeheader()
        writer.writerows(learning_rows)

    matched = sum(1 for row in rows if row["greeklex_rank"] != "")
    print(f"Wrote {len(rows)} rows to {args.output}")
    print(f"Wrote {len(learning_rows)} rows to {args.learning_output}")
    print(f"Matched {matched}; unmatched {len(rows) - matched}")


if __name__ == "__main__":
    main()
