"""Generate missing local secrets without changing existing configured values."""
from pathlib import Path
import secrets

KEYS = {'DB_PASSWORD', 'APP_DB_PASSWORD', 'JWT_SECRET'}

def configure(root: Path) -> int:
    target = root / '.env'
    source = target if target.exists() else root / '.env.example'
    lines = source.read_text().splitlines()
    seen = set()
    changed = 0
    for index, line in enumerate(lines):
        key, separator, value = line.partition('=')
        key = key.strip()
        if separator and key in KEYS:
            if key in seen:
                raise ValueError(f'Duplicate {key} in .env; resolve it before setup')
            seen.add(key)
            if value.strip() in ('', '""', "''"):
                lines[index] = f'{key}={secrets.token_hex(32)}'
                changed += 1
    for key in sorted(KEYS - seen):
        lines.append(f'{key}={secrets.token_hex(32)}')
        changed += 1
    target.write_text('\n'.join(lines) + '\n')
    target.chmod(0o600)
    return changed

if __name__ == '__main__':
    count = configure(Path(__file__).resolve().parents[1])
    print(f'.env ready: generated {count} missing values; existing values preserved.')
