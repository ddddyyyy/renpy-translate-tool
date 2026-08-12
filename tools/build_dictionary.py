"""Build the bundled high-value subset of ECDICT."""

import csv
import sqlite3
import sys
from pathlib import Path


def wanted(row):
    bnc = int(row["bnc"] or 0)
    frq = int(row["frq"] or 0)
    return bool(row["translation"].strip()) and (
        int(row["collins"] or 0) > 0
        or int(row["oxford"] or 0) > 0
        or bool(row["tag"])
        or 0 < bnc <= 30_000
        or 0 < frq <= 30_000
    )


def main():
    source, target = map(Path, sys.argv[1:3])
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target)
    connection.executescript("DROP TABLE IF EXISTS dictionary; CREATE TABLE dictionary (word TEXT PRIMARY KEY COLLATE NOCASE, phonetic TEXT NOT NULL, translation TEXT NOT NULL);")
    with source.open(encoding="utf-8", newline="") as file:
        rows = (
            (row["word"].strip(), row["phonetic"].strip(), row["translation"].strip())
            for row in csv.DictReader(file)
            if wanted(row)
        )
        connection.executemany("INSERT OR IGNORE INTO dictionary VALUES (?, ?, ?)", rows)
    connection.commit()
    connection.execute("VACUUM")
    print(connection.execute("SELECT COUNT(*) FROM dictionary").fetchone()[0])
    connection.close()


if __name__ == "__main__":
    main()
