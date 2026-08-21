#!/usr/bin/env python3
"""Delete a term archive by its unique label. No UI path.

Local:   python delete_archive.py "Spring 26"
Railway: railway run python delete_archive.py "Spring 26"
"""
import sys

from app import fetchone, execute, get_db


def main():
    if len(sys.argv) != 2:
        print('Usage: python delete_archive.py "Term Label"', file=sys.stderr)
        sys.exit(2)
    label = sys.argv[1]
    conn = get_db()
    row = fetchone(conn, "SELECT label FROM term_archives WHERE label=?", (label,))
    if not row:
        conn.close()
        print(f'No archive named {label!r}', file=sys.stderr)
        sys.exit(1)
    execute(conn, "DELETE FROM term_archives WHERE label=?", (label,))
    conn.commit()
    conn.close()
    print(f'Deleted archive {label!r}')


if __name__ == '__main__':
    main()
